import datetime
import hashlib
import hmac
import json
import logging
import os
import random
import threading
import time
from typing import Union
from wsgiref.simple_server import make_server

import openai
from pyramid.config import Configurator
from pyramid.request import Request
from pyramid.response import Response
from slack_bolt import App

from nameLookup import nameLookup

logging.basicConfig(level=logging.INFO)

lock = threading.Lock()

SECRETS = json.loads(os.getenv("SECRETS"))

openai.api_key = SECRETS["OPENAI_API_KEY"]
slack_signing_secret = SECRETS["SLACK_SIGNING_SECRET"]

# Initializes the app with bot token and signing secret
slackapp = App(
    token=SECRETS["SLACK_BOT_TOKEN"],
    signing_secret=slack_signing_secret
)

# Access to the web api client
client = slackapp.client
nameLookup = nameLookup(client, name=("PhilGPT", "Phil Barbeau"))


def is_valid_request(
        body: Union[str, bytes],
        timestamp: str,
        signature: str,
) -> bool:
    """Verifies if the given signature is valid
    Stolen from slack_sdk/signature
    body must be json without whitespace in separators
    """
    if timestamp is None or signature is None or body is None:
        return False

    if isinstance(body, bytes):
        body = body.decode("utf-8")

    format_req = str.encode(f"v0:{timestamp}:{body}")
    encoded_secret = str.encode(slack_signing_secret)
    request_hash = hmac.new(encoded_secret, format_req, hashlib.sha256).hexdigest()
    calculated_signature = f"v0={request_hash}"

    if calculated_signature is None:
        return False
    return hmac.compare_digest(calculated_signature, signature)


def reply(
        body: dict
) -> str:
    channel = body["event"]["channel"]
    ts = body["event"]["ts"]
    text = body["event"]["text"]

    # Get history
    # Can't limit because then we only get the oldest messages
    result = client.conversations_history(
        channel=channel,
        inclusive=True,
        oldest=str(float(ts) - 1 * 60 * 60)
    )

    length = 0
    prompt = ""
    for otherMsg in result["messages"]:
        if float(otherMsg['ts']) < float(ts) - 8 * 60 * 60: break  # We only want messages < 1 hours old
        if 'subtype' in otherMsg: continue  # Get rid of weird messages
        if "<http" in otherMsg['text']:  # Get rid of links
            continue
        if "user" not in otherMsg: continue
        length += 1
        user = nameLookup.lookupName(otherMsg.get('user'))
        prompt = "%s: %s\n" % (user, nameLookup.sanitizeMessage(otherMsg['text'].strip())) + prompt
        if length >= 5: break

    prompt += "Phil Barbeau:"

    # Post a picture if we're asked for one!
    if ('picture' in text.lower()) or ('image' in text.lower()):
        postImage(channel, prompt, showText=False)
    postMessage(channel, prompt)


def postImage(channel, prompt, showText=True):
    response = openai.Completion.create(
        # model="curie:ft-personal-2023-07-04-05-59-02",
        model="curie:ft-personal:phil-gpt-2023-06-15-04-19-27",
        prompt=prompt,
        max_tokens=100,
        temperature=0.85,
        presence_penalty=-0.2,
        frequency_penalty=0.8,
        best_of=10,
        stop="\n",
        logit_bias={"25": -1.1,
                    "2633": -0.5,
                    "36251": -0.5,
                    "14511": -0.5,
                    "4386": -0.5,
                    "18886": -0.1,
                    "62": -1.1}  # Penalize emoji keywords and semicolons
    )
    philGPToutput = response["choices"][0]["text"].strip()

    response = openai.ChatCompletion.create(
        model="gpt-3.5-turbo",
        messages=[
            {"role": "system", "content": "Describe an image based on the following prompt in 100 words or less."},
            {"role": "user", "content": philGPToutput}
        ]
    )
    imagePrompt = response["choices"][0]["message"]["content"].strip()
    logging.info(f"Image prompt: %s" % imagePrompt)

    response = openai.Image.create(
        prompt=imagePrompt,
        n=1,
        size="1024x1024"
    )
    text = philGPToutput if showText else ''
    image_url = response['data'][0]['url']
    attachments = [{"title": "A drawing by PhilGPT", "image_url": image_url}]
    client.chat_postMessage(channel=channel, text=text,
                            attachments=attachments)


def postMessage(channel, prompt):
    response = openai.Completion.create(
        # model="curie:ft-personal-2023-07-04-05-59-02",
        model="curie:ft-personal:phil-gpt-2023-06-15-04-19-27",
        prompt=prompt,
        max_tokens=100,
        temperature=0.85,
        presence_penalty=-0.2,
        frequency_penalty=0.8,
        best_of=10,
        stop="\n",
        logit_bias={"25": -1.1,
                    "2633": -0.5,
                    "36251": -0.5,
                    "14511": -0.5,
                    "4386": -0.5,
                    "18886": -0.1,
                    "62": -1.1}  # Penalize emoji keywords and semicolons
    )
    output = response["choices"][0]["text"].strip()
    client.chat_postMessage(
        channel=channel,
        text=output
    )
    logging.info(f"Prompt:%s" % prompt)
    logging.info(f"Response:%s" % output)


def event_listener(
        request: Request
) -> Response:
    try:
        request_json = request.json
        if request_json["type"] == "url_verification":
            return Response(
                content_type="text/plain",
                body=request_json["challenge"]
            )

        headers = request.headers
        slack_signature = headers['x-slack-signature']
        slack_time = headers['x-slack-request-timestamp']
        logging.info(f"Request with timestamp %s and signature %s" % (slack_time, slack_signature))

        # Verify this is a valid request
        if is_valid_request(json.dumps(request_json, separators=(',', ':')), slack_time, slack_signature):
            if request_json["event"]["type"] == "app_mention":
                t = threading.Thread(target=reply, args=[request_json])
                t.start()
                return Response(body="I'm a slackbot working hard! beep boop", status_code=200)
    except (KeyError, json.JSONDecodeError):
        pass

    return Response(status_code=403)


def randomMessages():
    prompt = r"What are you up to Phil Barbeau?\nPhil Barbeau:"
    waitTime = random.randint(24 * 60 * 60, 3 * 24 * 60 * 60)  # Seconds
    while True:
        postTime = datetime.datetime.now(tz=datetime.timezone.utc) + datetime.timedelta(seconds=waitTime, hours=-4)
        logging.info(f"Message will be posted at %s %s UTC-4" % (postTime.date(), postTime.time()))
        time.sleep(waitTime)
        postMessage("random", prompt)
        waitTime = random.randint(24 * 60 * 60, 3 * 24 * 60 * 60)  # Seconds


def randomPictures():
    prompt = r"Describe a cool scene Phil Barbeau\nPhil Barbeau:"
    waitTime = 120  # seconds
    while True:
        postTime = datetime.datetime.now(tz=datetime.timezone.utc) + datetime.timedelta(seconds=waitTime, hours=-4)
        logging.info(f"Image will be posted at %s %s UTC-4" % (postTime.date(), postTime.time()))
        time.sleep(waitTime)
        postImage("random", prompt)
        waitTime = random.randint(24 * 60 * 60, 3 * 24 * 60 * 60)  # Seconds


if __name__ == '__main__':
    t = threading.Thread(target=randomMessages)
    t.start()
    t2 = threading.Thread(target=randomPictures)
    t2.start()
    port = int(os.environ.get("PORT", 3000))
    with Configurator() as config:
        config.add_route('listener', '/')
        config.add_view(event_listener, route_name='listener')
        app = config.make_wsgi_app()
    server = make_server('0.0.0.0', port, app)
    server.serve_forever()
