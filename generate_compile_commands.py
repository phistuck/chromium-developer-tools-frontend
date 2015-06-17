import json

JSON_FILE_NAMES = ["inspector.json", "toolbox.json"]
JSON_PATH = "./devtools/front_end/"

COMMAND_LINE = "python -u ./devtools/scripts/compile_frontend.py "

modules = set();
for file_name in JSON_FILE_NAMES:
 for module in json.load(open(JSON_PATH + file_name)):
  modules.add(module["name"])
output_script = open("./compile_frontend_separetely.sh", 'w+')
output_script.write("final_code=0\n")
for module in modules:
 output_script.write("echo Compiling " + module + "...\n")
 output_script.write(COMMAND_LINE + module + "\n")
 output_script.write("current_code=$?; ")
 output_script.write("if [[ $current_code != 0 ]]; then final_code=1; fi\n")
output_script.write("exit $final_code")
output_script.close()