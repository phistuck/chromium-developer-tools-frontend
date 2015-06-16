import json

JSON_FILE_NAMES = ["inspector.json", "toolbox.json"]
JSON_PATH = "./devtools/front_end/"

COMMAND_LINE = "python -u ./devtools/scripts/compile_frontend.py "

modules = set();
for file_name in JSON_FILE_NAMES:
 for module in json.load(open(JSON_PATH + file_name)):
  modules.add(module["name"])
output_script = open("./compile_frontend_separetely.sh", 'w+')
for module in modules:
 output_script.write("echo Compiling " + module + "...\n" + COMMAND_LINE + module + "\n")
output_script.close()