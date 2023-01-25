#!/bin/sh -l
python /main.py --openai_api_key "$1" --github_token "$2" --github_pr_id "$3"