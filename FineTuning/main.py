import os, glob, json
from re import Match

import jsonlines
from datetime import datetime
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
import re
import tiktoken

encoding = tiktoken.get_encoding("r50k_base")

slackClient = WebClient(token=os.environ["SLACK_API_TOKEN"])
philUser = os.environ["PHIL_USERNAME"]

names = {}

def apiLookup(name):
    try:
        return names[name]
    except KeyError:
        names[name] = slackClient.users_info(user=name)
        return names[name]


def lookupName(id: str) -> str:
    name = ""
    try:
        name = apiLookup(id)['user']['profile']['real_name']
    except KeyError:
        pass
    if name != "": return name

    try:
        name = apiLookup(id)['user']['real_name']
    except KeyError:
        pass
    if name != "": return

    try:
        name = apiLookup(id)['user']['profile']['name']
    except KeyError:
        pass
    if name != "": return name

    return "Student" # fallback


def RElookupName(match: Match | None) -> str:
    return lookupName(match.group(1))


def sanitizeMessage(msg: str) -> str:
    new = re.sub(r"<@(.*?)>", RElookupName, msg)
    new = re.sub(r"<!(.*?)>", "\1", new)
    return new

count = 0
tokens = 0

with jsonlines.open("payload.jsonl", 'w') as writer:
    for channel in glob.glob('../slack/*'):
        channelname = os.path.basename(os.path.normpath(channel))
        if channelname not in ["general", "random"]: continue
        messages = [] # list of dicts
        for filename  in glob.glob(channel + '/*.json'):
            with open(filename,'r') as f:
                messages.extend(json.load(f)) # .json is list of dicts
        messages.sort(key=lambda msg: msg['ts'])  # sort by timestamp

        for i, philMsg in enumerate(messages):
            hasLink = False
            length = 0

            ts = float(philMsg.get('ts'))
            packet = {}
            packet["prompt"] = ""

            if philMsg.get('user') != philUser: continue # Look for phil messages
            if 'subtype' in philMsg: continue # get rid of auto messages?
            if "<http" in philMsg['text']: continue # get rid of Phil links
            if philMsg['text'].strip() == "": continue # get rid of whitespace only
            if "\n" in philMsg['text']: continue
            if len(philMsg['text']) < 20: continue
            if len(philMsg['text']) > 100: continue

            for j in range(i-1, 0, -1):
                otherMsg = messages[j]
                if float(otherMsg['ts']) < ts - 60*60*8: break # 8 hours
                if 'subtype' in otherMsg: break
                if "<http" in otherMsg['text']:
                    hasLink = True
                    break
                if "user" not in otherMsg: break
                length += 1
                user = lookupName(otherMsg.get('user'))
                packet["prompt"] = "%s: %s\n" % (user, sanitizeMessage(otherMsg['text'].strip())) + packet["prompt"]
                if length >= 3: break

            if(length > 1 and not hasLink):
                packet["prompt"] += "Phil Barbeau:"
                # packet["prompt"] = "Slack channel: %s\n\n###\n\n" % channelname + packet["prompt"]
                packet["completion"] = " %s\n" % sanitizeMessage(philMsg['text'].strip())
                writer.write(packet)
                count += 1
                print("Channel: ", channelname, datetime.fromtimestamp(ts), length)
                print("Original message: ", sanitizeMessage(philMsg['text'].strip()))

                tokens += len(encoding.encode(packet["prompt"]))
                tokens += len(encoding.encode(packet["completion"]))

    print(count)
    print("Estimated cost: ", tokens*0.0000015*7.5)