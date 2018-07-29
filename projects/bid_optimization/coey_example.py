import sys
import os
import re
import time
import json
import random
import uuid
import urllib
import requests
import argparse
import traceback
import subprocess
import dialogflow
from contextlib import closing
from slackclient import SlackClient

try:
    import configparser
except ImportError:
    sys.path.insert(0, "/Users/jbaker/anaconda3/envs/py36/lib/python3.6/site-packages")
    import configparser


def detect_intent_texts(project_id, session_id, text, language_code):
    """Returns the result of detect intent with texts as inputs.

    Using the same `session_id` between requests allows continuation
    of the conversaion."""
    session_client = dialogflow.SessionsClient()
    session = session_client.session_path(project_id, session_id)

    # print('Session path: {}\n'.format(session))

    out_text = ''
    # for text in texts:
    text_input = dialogflow.types.TextInput(
        text=text, language_code=language_code)

    query_input = dialogflow.types.QueryInput(text=text_input)

    response = session_client.detect_intent(
        session=session, query_input=query_input)

    out_text = response.query_result.fulfillment_text

    return out_text

def get_user_name(user_id):
    """Helper function to get a Slack user's real, full name, given their ID

    Args:
        user_id         string

    Returns:
         Either the full, real name, or the shorter 'name' from the Slack API

    """
    user_info = slack_client.api_call('users.info', user=user_id)

    if user_info['user']['real_name']:
        return user_info['user']['real_name']
    elif user_info['name']:
        return user_info['name']
    else:
        return None

def help_menu():
    """Helper function returning the Coey help menu
    """
    return """ ```
    Possible Commands are:
        help

        Coey:
            show summary for <campaign_id>
            show current margin <ad grop id>

        About the Coeybot:
            who are you?
            how old are you?
            xkcd

        Examples:
            '@hCoey who are you?'
            '@Coey show summary for 'xx3uy4etejjsrrt'
            '@Coey show current margin '23409864'

    ```"""

def handle_command(command, channel, name_of_user, gcp_df_project_id, testing = None, context = None):
    """
    Receives commands directed at the bot and determines if they
    are valid commands. If so, then acts on the commands. If not,
    returns back what it needs for clarification.

    Args:
        command:        Text that came after @Coey or in a DM (str)
        channel:        Channel on which to post response (int, str)
        name_of_user:   Full name of person who spoke to Coey (str)
        testing:        Testing flag (int)
        context:        API.AI context (string)

    Returns:
        response:       A response, posted to the Slack API

    """

    # General setup

    attachment = []
    pretext = ''
    autostop_response = None
    new_context = None
    first_name_of_user = name_of_user.split()[0]

    if testing == 1:
        pretext += '(Please note: I am currently under testing) '

    # Every time you speak to Coey, she'll greet you with a random pleasantry
    pleasantries = ['Certainly', 'Of course', 'Sure', 'No problem', \
                    'Happy to help', 'Yes', 'Sounds good', 'Sounds great']

    if re.search(r'help$', command, flags=re.I):
        pretext += '{}, {}. '.format(random.choice(pleasantries), first_name_of_user)
        pretext += help_menu()

    # elif command.startswith("xkcd"):
    elif re.search(r'xkcd', command, flags=re.I):
        xkcd_base_url = "https://xkcd.com/info.0.json"
        r = requests.get(xkcd_base_url)
        xkcd_max = r.json()['num']

        random_comic_index = random.randint(1, xkcd_max)
        comic_url = requests.get(xkcd_base_url.format(random_comic_index))
        pretext += comic_url.json()['img']

    elif re.search(r'show number of (.*) in (\d+|\w\w)$', command, flags=re.I):
        s = re.search(r'show number of (.*) in (\d+|\w\w)$', command, flags=re.I)
        if s.group(1) and s.group(2):
            try:
                # Return Chart
                command = "python build_graphs.py --ht_id " \
                          + ht_id[0] \
                          + " --chart_to_build margin-over-time" \
                          + " --slack_channel {}".format(channel)

                subprocess.run(command, shell=True, check=True)

                pretext += "Are those helpful?"

            except (IndexError, ValueError, TypeError, subprocess.CalledProcessError):
                pretext += " Sorry, I am having trouble finding that campaign ID. Please try again."

                traceback.print_exc()
    else:
        pretext += detect_intent_texts(gcp_df_project_id, str(uuid.uuid4()), command, 'en-us')

    attachment.insert(0, {'pretext': pretext, "mrkdwn_in": ['pretext']})

    # An ugly hack :/
    if autostop_response is None:
        slack_client.api_call("chat.postMessage",
                          channel=channel,
                          attachments = attachment,
                          as_user=True)
    else:
        slack_client.api_call("chat.postMessage",
                          channel=channel,
                          text = autostop_response,
                          as_user=True)

    return new_context


def parse_slack_output(slack_rtm_output):
    """
    The Slack Real Time Messaging API is an events firehose. this parsing function returns None unless a message is
    directed at the Bot, based on if the bot was called explicitly or if the channel is a direct message.
    """
    output_list = slack_rtm_output
    if output_list and len(output_list) > 0:
        for output in output_list:
            """
            checking to see if `@Coey` is used or if it is a direct message;
            channel and group check return dictionaries that have an `error` 
            and `ok` key. We expect the `ok` to be false for both if the channel 
            ID is from a direct message (because it wouldn't be listed as a public 
            channel or group). Direct messages have the first letter of the channel 
            ID == 'D' (using `or` because the channel ID == 'D' might change in the 
            future, says Slack)
            """
            if output and ('text' in output) and ('channel' in output):

                # Check to see if channel ID exists as a public channel or group
                channel_check = slack_client.api_call(
                    "channels.info",
                    channel=output['channel']
                )

                group_check = slack_client.api_call(
                    "groups.info",
                    channel=output['channel']
                )

                if (AT_BOT in output['text'] or
                        ((not any((channel_check['ok'],group_check['ok'])) or output['channel'][0] == 'D')
                         and output['user'] != BOT_ID)):
                    return output['text'].strip(), output['channel'], get_user_name(output['user'])

    return None, None, None


if __name__ == "__main__":
    # 1 second delay between reading from firehose
    READ_WEBSOCKET_DELAY = 1

    # Adding a flag that Coey is in 'testing mode' sometimes
    # This alerts users if he's currently being tested.
    parser = argparse.ArgumentParser()
    parser.add_argument("--testing", help = "Select 1 to enable Coey testing mode.", type = int)
    args = parser.parse_args()

    # Read Model Specific Configuration File
    settings = configparser.ConfigParser()
    settings.read(os.path.expanduser('~/.coey/coey.conf'))

    # BOT Variables
    BOT_CHANNEL = settings.get('Slack', 'slack_bot_channel')
    BOT_ID = settings.get('Slack', 'slack_bot_id')
    SLACK_BOT_TOKEN = settings.get('Slack', 'Bot_User_OAuth_Access_Token')
    AT_BOT = "<@{}>".format(BOT_ID)

    # DialogFlow Variables
    gcp_df_project_id = settings.get('DialogFlow', 'project_id')
    GCP_CRED = settings.get('DialogFlow', 'GOOGLE_APPLICATION_CREDENTIALS')
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = GCP_CRED

    # instantiate Slack clents
    slack_client = SlackClient(SLACK_BOT_TOKEN)

    try:
        slack_client.api_call(
            "chat.postMessage",
            channel="#general",
            text="Hello from Coey! :tada:",
            token=os.environ.get('SLACK_BOT_TOKEN')
        )

        if slack_client.rtm_connect():
            print("Coey is listening to you.")
            apiai_context = None

            while True:
                command, channel, user_name = parse_slack_output(slack_client.rtm_read())

                if command and channel and user_name:
                    apiai_context = handle_command(command, channel, user_name, gcp_df_project_id, args.testing,
                                                   apiai_context)
                time.sleep(READ_WEBSOCKET_DELAY)

        else:
            raise Exception("Connection failed. Network problem, invalid Slack token or bot ID?")

    except Exception as e:
        raise e
