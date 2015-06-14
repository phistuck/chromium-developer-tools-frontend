#!/usr/bin/env python

__version__ = '1.8.0'
# TODO(joi) Add caching where appropriate/needed. The API is designed to allow
# caching (between all different invocations of presubmit scripts for a given
# change). We should add it as our presubmit scripts start feeling slow.
import cpplint
import cPickle  # Exposed through the API.
import cStringIO  # Exposed through the API.
import contextlib
import fnmatch
import glob
import inspect
import itertools
import json  # Exposed through the API.
import logging
import marshal  # Exposed through the API.
import multiprocessing
import optparse
import os  # Somewhat exposed through the API.
import pickle  # Exposed through the API.
import random
import re  # Exposed through the API.
import sys  # Parts exposed through API.
import tempfile  # Exposed through the API.
import time
import traceback  # Exposed through the API.
import types
import unittest  # Exposed through the API.
import urllib2  # Exposed through the API.
from warnings import warn
# Local imports.
import auth
import fix_encoding
import gclient_utils
import owners
import presubmit_canned_checks
import rietveld
import scm
import subprocess2 as subprocess  # Exposed through the API.
# Ask for feedback only once in program lifetime.
_ASKED_FOR_FEEDBACK = False

class InputApi(object):
  """An instance of this object is passed to presubmit scripts so they can
  know stuff about the change they're looking at.
  """
  # Method could be a function
  # pylint: disable=R0201
  # File extensions that are considered source files from a style guide
  # perspective. Don't modify this list from a presubmit script!
  #
  # Files without an extension aren't included in the list. If you want to
  # filter them as source files, add r"(^|.*?[\\\/])[^.]+$" to the white list.
  # Note that ALL CAPS files are black listed in DEFAULT_BLACK_LIST below.
  DEFAULT_WHITE_LIST = (
      # C++ and friends
      r".+\.c$", r".+\.cc$", r".+\.cpp$", r".+\.h$", r".+\.m$", r".+\.mm$",
      r".+\.inl$", r".+\.asm$", r".+\.hxx$", r".+\.hpp$", r".+\.s$", r".+\.S$",
      # Scripts
      r".+\.js$", r".+\.py$", r".+\.sh$", r".+\.rb$", r".+\.pl$", r".+\.pm$",
      # Other
      r".+\.java$", r".+\.mk$", r".+\.am$", r".+\.css$"
  )
  # Path regexp that should be excluded from being considered containing source
  # files. Don't modify this list from a presubmit script!
  DEFAULT_BLACK_LIST = (
      r"testing_support[\\\/]google_appengine[\\\/].*",
      r".*\bexperimental[\\\/].*",
      r".*\bthird_party[\\\/].*",
      # Output directories (just in case)
      r".*\bDebug[\\\/].*",
      r".*\bRelease[\\\/].*",
      r".*\bxcodebuild[\\\/].*",
      r".*\bout[\\\/].*",
      # All caps files like README and LICENCE.
      r".*\b[A-Z0-9_]{2,}$",
      # SCM (can happen in dual SCM configuration). (Slightly over aggressive)
      r"(|.*[\\\/])\.git[\\\/].*",
      r"(|.*[\\\/])\.svn[\\\/].*",
      # There is no point in processing a patch file.
      r".+\.diff$",
      r".+\.patch$",
  )
  def __init__(self, change, presubmit_path, is_committing,
      rietveld_obj, verbose):
    """Builds an InputApi object.
    Args:
      change: A presubmit.Change object.
      presubmit_path: The path to the presubmit script being processed.
      is_committing: True if the change is about to be committed.
      rietveld_obj: rietveld.Rietveld client object
    """
    # Version number of the presubmit_support script.
    self.version = [int(x) for x in __version__.split('.')]
    self.change = change
    self.is_committing = is_committing
    self.rietveld = rietveld_obj
    # TBD
    self.host_url = 'http://codereview.chromium.org'
    if self.rietveld:
      self.host_url = self.rietveld.url
    # We expose various modules and functions as attributes of the input_api
    # so that presubmit scripts don't have to import them.
    self.basename = os.path.basename
    self.cPickle = cPickle
    self.cpplint = cpplint
    self.cStringIO = cStringIO
    self.glob = glob.glob
    self.json = json
    self.logging = logging.getLogger('PRESUBMIT')
    self.os_listdir = os.listdir
    self.os_walk = os.walk
    self.os_path = os.path
    self.os_stat = os.stat
    self.pickle = pickle
    self.marshal = marshal
    self.re = re
    self.subprocess = subprocess
    self.tempfile = tempfile
    self.time = time
    self.traceback = traceback
    self.unittest = unittest
    self.urllib2 = urllib2
    # To easily fork python.
    self.python_executable = sys.executable
    self.environ = os.environ
    # InputApi.platform is the platform you're currently running on.
    self.platform = sys.platform
    self.cpu_count = multiprocessing.cpu_count()
    # The local path of the currently-being-processed presubmit script.
    self._current_presubmit_path = os.path.dirname(presubmit_path)
    # We carry the canned checks so presubmit scripts can easily use them.
    self.canned_checks = presubmit_canned_checks
    # TODO(dpranke): figure out a list of all approved owners for a repo
    # in order to be able to handle wildcard OWNERS files?
    self.owners_db = owners.Database(change.RepositoryRoot(),
        fopen=file, os_path=self.os_path, glob=self.glob)
    self.verbose = verbose
    self.Command = CommandData
    # Replace <hash_map> and <hash_set> as headers that need to be included
    # with "base/containers/hash_tables.h" instead.
    # Access to a protected member _XX of a client class
    # pylint: disable=W0212
    self.cpplint._re_pattern_templates = [
      (a, b, 'base/containers/hash_tables.h')
        if header in ('<hash_map>', '<hash_set>') else (a, b, header)
      for (a, b, header) in cpplint._re_pattern_templates
    ]
  def PresubmitLocalPath(self):
    """Returns the local path of the presubmit script currently being run.
    This is useful if you don't want to hard-code absolute paths in the
    presubmit script.  For example, It can be used to find another file
    relative to the PRESUBMIT.py script, so the whole tree can be branched and
    the presubmit script still works, without editing its content.
    """
    return self._current_presubmit_path
  def DepotToLocalPath(self, depot_path):
    """Translate a depot path to a local path (relative to client root).
    Args:
      Depot path as a string.
    Returns:
      The local path of the depot path under the user's current client, or None
      if the file is not mapped.
      Remember to check for the None case and show an appropriate error!
    """
    return scm.SVN.CaptureLocalInfo([depot_path], self.change.RepositoryRoot()
        ).get('Path')
  def LocalToDepotPath(self, local_path):
    """Translate a local path to a depot path.
    Args:
      Local path (relative to current directory, or absolute) as a string.
    Returns:
      The depot path (SVN URL) of the file if mapped, otherwise None.
    """
    return scm.SVN.CaptureLocalInfo([local_path], self.change.RepositoryRoot()
        ).get('URL')
  def AffectedFiles(self, include_dirs=False, include_deletes=True,
                    file_filter=None):
    """Same as input_api.change.AffectedFiles() except only lists files
    (and optionally directories) in the same directory as the current presubmit
    script, or subdirectories thereof.
    """
    dir_with_slash = normpath("%s/" % self.PresubmitLocalPath())
    if len(dir_with_slash) == 1:
      dir_with_slash = ''
    return filter(
        lambda x: normpath(x.AbsoluteLocalPath()).startswith(dir_with_slash),
        self.change.AffectedFiles(include_dirs, include_deletes, file_filter))
  def LocalPaths(self, include_dirs=False):
    """Returns local paths of input_api.AffectedFiles()."""
    paths = [af.LocalPath() for af in self.AffectedFiles(include_dirs)]
    logging.debug("LocalPaths: %s", paths)
    return paths
  def AbsoluteLocalPaths(self, include_dirs=False):
    """Returns absolute local paths of input_api.AffectedFiles()."""
    return [af.AbsoluteLocalPath() for af in self.AffectedFiles(include_dirs)]
  def ServerPaths(self, include_dirs=False):
    """Returns server paths of input_api.AffectedFiles()."""
    return [af.ServerPath() for af in self.AffectedFiles(include_dirs)]
  def AffectedTextFiles(self, include_deletes=None):
    """Same as input_api.change.AffectedTextFiles() except only lists files
    in the same directory as the current presubmit script, or subdirectories
    thereof.
    """
    if include_deletes is not None:
      warn("AffectedTextFiles(include_deletes=%s)"
               " is deprecated and ignored" % str(include_deletes),
           category=DeprecationWarning,
           stacklevel=2)
    return filter(lambda x: x.IsTextFile(),
                  self.AffectedFiles(include_dirs=False, include_deletes=False))
  def FilterSourceFile(self, affected_file, white_list=None, black_list=None):
    """Filters out files that aren't considered "source file".
    If white_list or black_list is None, InputApi.DEFAULT_WHITE_LIST
    and InputApi.DEFAULT_BLACK_LIST is used respectively.
    The lists will be compiled as regular expression and
    AffectedFile.LocalPath() needs to pass both list.
    Note: Copy-paste this function to suit your needs or use a lambda function.
    """
    def Find(affected_file, items):
      local_path = affected_file.LocalPath()
      for item in items:
        if self.re.match(item, local_path):
          logging.debug("%s matched %s" % (item, local_path))
          return True
      return False
    return (Find(affected_file, white_list or self.DEFAULT_WHITE_LIST) and
            not Find(affected_file, black_list or self.DEFAULT_BLACK_LIST))
  def AffectedSourceFiles(self, source_file):
    """Filter the list of AffectedTextFiles by the function source_file.
    If source_file is None, InputApi.FilterSourceFile() is used.
    """
    if not source_file:
      source_file = self.FilterSourceFile
    return filter(source_file, self.AffectedTextFiles())
  def RightHandSideLines(self, source_file_filter=None):
    """An iterator over all text lines in "new" version of changed files.
    Only lists lines from new or modified text files in the change that are
    contained by the directory of the currently executing presubmit script.
    This is useful for doing line-by-line regex checks, like checking for
    trailing whitespace.
    Yields:
      a 3 tuple:
        the AffectedFile instance of the current file;
        integer line number (1-based); and
        the contents of the line as a string.
    Note: The carriage return (LF or CR) is stripped off.
    """
    files = self.AffectedSourceFiles(source_file_filter)
    return _RightHandSideLinesImpl(files)
  def ReadFile(self, file_item, mode='r'):
    """Reads an arbitrary file.
    Deny reading anything outside the repository.
    """
    if isinstance(file_item, AffectedFile):
      file_item = file_item.AbsoluteLocalPath()
    if not file_item.startswith(self.change.RepositoryRoot()):
      raise IOError('Access outside the repository root is denied.')
    return gclient_utils.FileRead(file_item, mode)
  @property
  def tbr(self):
    """Returns if a change is TBR'ed."""
    return 'TBR' in self.change.tags
  def RunTests(self, tests_mix, parallel=True):
    tests = []
    msgs = []
    for t in tests_mix:
      if isinstance(t, OutputApi.PresubmitResult):
        msgs.append(t)
      else:
        assert issubclass(t.message, _PresubmitResult)
        tests.append(t)
        if self.verbose:
          t.info = _PresubmitNotifyResult
    if len(tests) > 1 and parallel:
      pool = multiprocessing.Pool()
      # async recipe works around multiprocessing bug handling Ctrl-C
      msgs.extend(pool.map_async(CallCommand, tests).get(99999))
      pool.close()
      pool.join()
    else:
      msgs.extend(map(CallCommand, tests))
    return [m for m in msgs if m]


def main(argv = None):
 print("Here")
 change = InputApi("", "./devtools", False, None, True)
 #PRESUBMIT.CheckChangeOnUpload(change)
 print(change)
 return 0

sys.exit(main())
