import requests
import json
import os
from termcolor import colored
from argparse import ArgumentParser, RawDescriptionHelpFormatter


def zenpload(url, filename, content_type, data):
    req = requests.post(f"{url}?filename={filename}", headers={"Content-Type": content_type}, data=data)
    return req.status_code, req.json()


parser = ArgumentParser(formatter_class=RawDescriptionHelpFormatter,
    description=("Zenploader is a script which takes advantage of zendesk help desks uploading api to upload files onto it."))
parser.add_argument("--plain", "-p", type=str, dest="PLAIN", help="Lets you upload plain content.")
parser.add_argument("--file", "-f", type=str, dest="FILE", help="Provide a file (directory of file if needed)")
parser.add_argument("--config", "-c", type=str, dest="CFG", help="This lets you use a alternative config file (directory of config file if needed)")
parser.add_argument("--url", "-u", type=str, dest="URL", help="Lets you use an alternative url without needing to add it to the config.")
args = parser.parse_args()


#checking the url params and deciding what to do
if args.URL != None:
    siteoption = False
    soption = args.URL
    ctype = True
else:
    siteoption = True


#file and plain content checking
if args.FILE and args.PLAIN != None:
    print(colored("Please choose only, either plain content or file.", "red"))
    
elif args.PLAIN != None:
    ufile = args.PLAIN
elif args.FILE != None:
    try:
        ufile = open(args.FILE, 'rb')
    except FileNotFoundError:
        print(colored("File not found", "red"))
        
else:
    print(colored("Not all options may be supported.\nRun the command -h for a list of commands.", "red"))
    COMMAND = input('cmd: ')
    print('\033[H\033[J')
    os.system('python zenploader.py ' + COMMAND)
    os.system('python zenploader.py')
    


#config checking
if args.CFG != None:
    try:
        cfg = json.loads(open("config.json", "r").read())
    except json.decoder.JSONDecodeError:
        print(colored("The JSON file isn't valid, there was an error reading it.", "red"))
        
    except FileNotFoundError:
        print(colored("The config file is missing, try reloading this tool!", "red"))
        
else:
    try:
        cfg = json.loads(open("config.json", "r").read())
    except json.decoder.JSONDecodeError:
        print(colored("The JSON file isn't valid, there was an error reading it.", "red"))
        
    except FileNotFoundError:
        print(colored("The config file is missing, try reloading this tool!", "red"))
        


#Choosing which site to upload to
print('\033[H\033[J')
while siteoption:
    try:
        opts = []
        for i in cfg['sites']:
            if 'name' and 'url' in i:
                print(f"{colored(len(opts) + 1, 'green')}. {i['name']}")
                opts.append(i)
            else:
                pass
        soption = int(input(f"Select which one to upload to ({colored(f'1-{len(opts)}', 'green')}) \n"))
        if soption <= 0:
            raise IndexError("Out of range")
        soption = opts[soption - 1]["url"]
        opts.clear()
        siteoption = False
        ctype = True
        print('\033[H\033[J')
    except ValueError:
        print('\033[H\033[J')
        print(colored(f"Make sure you put in a number which is between {colored(f'1-{len(opts)}', 'green')}", "red"))
        continue
    except IndexError:
        print('\033[H\033[J')
        print(colored(f"Please select a number between {colored(f'1-{len(opts)}', 'green')}", "red"))
        continue


#Choosing content type category
while ctype:
    try:
        opts = ["text", "image", "video", "audio", "application", "multipart", "vnd"]
        print(f"{colored(1, 'green')}. Text\n{colored(2, 'green')}. Image\n{colored(3, 'green')}. Video\n{colored(4, 'green')}. Audio\n{colored(5, 'green')}. Application\n{colored(6, 'green')}. Multipart\n{colored(7, 'green')}. vnd")
        ctype = int(input(f"Select content type category ({colored(f'1-{len(opts)}', 'green')}) \n"))
        if ctype <= 0:
            raise IndexError("Out of range")
        coption = cfg['content-types'][opts[ctype - 1]]
        opts.clear()
        ctype = False
        echoices = True
        print('\033[H\033[J')
    except IndexError:
        print('\033[H\033[J')
        print(colored(f"Please select a number between {colored(f'1-7', 'green')}", "red"))
        continue


#Choosing the exact content type
while echoices:
    try:
        opts = []
        for i in coption:
            if 'value' in i:
                print(f"{colored(len(opts) + 1, 'green')}. {i['value']}")
                opts.append(i)
            else:
                pass
        echoice = int(input(f"Select content type ({colored(f'1-{len(opts)}', 'green')}) \n"))
        if echoice <= 0:
            raise IndexError("Out of range")
        echoice = opts[echoice - 1]
        opts.clear()
        echoices = False
        ninput = True
        print('\033[H\033[J')
    except ValueError:
        print('\033[H\033[J')
        print(f"{colored('Make sure you put in a number which is between')} {colored(f'1-{len(opts)}', 'green')}", 'red')
        continue
    except IndexError:
        print('\033[H\033[J')
        print(colored(f"Please select a number between {colored(f'1-{len(opts)}', 'green')}", "red"))
        continue


#Asks for a file name which will be in the url
while ninput:
    fname = input("Name of the file? ")
    if len(fname) <= 2048:
        ninput = False
    else:
        print(colored("Name is too long!", "red"))

try:
    res = zenpload(url=soption, filename=fname, content_type=echoice['value'], data=ufile)
except json.decoder.JSONDecodeError:
    print(colored("Error decoding response JSON", "red"))
    
except requests.exceptions.ConnectTimeout:
    print(colored("Connection timeout", "red"))
except requests.exceptions.ConnectionError:
    print(colored("Connection error", "red"))
    
except requests.exceptions.MissingSchema:
    print(colored("URL is invalid, make sure it is formatted right!", "red"))
    

if res[0] == 201:
    print(colored('-----------------', 'green'))
    print(f'Expires at {res[1]["upload"]["expires_at"]}\nURL: {res[1]["upload"]["attachments"][0]["mapped_content_url"]}')
else:
    print(colored("Error has occurred while uploading", "red"))