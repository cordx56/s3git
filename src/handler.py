import os
import shutil
import urllib.parse
import json
import traceback
import git
import boto3
from boto3_type_annotations.s3 import Client
from aws_lambda_typing import events, context

s3: Client = boto3.client("s3")

def handler(event: events.S3Event, context: context.Context):
    try:
        actor = git.Actor("cordx56", "obsidian-s3@example.com")
        repo_path = os.path.join("/tmp", "repo")
        if os.path.isdir(repo_path):
            shutil.rmtree(repo_path)
        repo = git.Repo.clone_from(os.environ["GIT_ORIGIN"], repo_path, multi_options=["--depth 1"])
        indexed = []
        for record in event["Records"]:
            bucket = record["s3"]["bucket"]["name"]
            key = record["s3"]["object"]["key"]
            parsed = urllib.parse.unquote_plus(key)
            response = s3.get_object(Bucket=bucket, Key=parsed)

            path = os.path.join(repo_path, key)
            if repo.ignored(path):
                continue
            if record["eventName"].startswith("ObjectRemoved"):
                try:
                    os.remove(path)
                    indexed.append(path)
                except FileNotFoundError:
                    pass
            elif record["eventName"].startswith("ObjectCreated"):
                dirname = os.path.dirname(path)
                if not os.path.isdir(dirname):
                    os.makedirs(dirname)
                with open(path, "wb") as f:
                    f.write(response["Body"].read())
                    size = f.tell()
                if size < 10000000: # 10MiB
                    indexed.append(path)
        repo.index.add(indexed, force=False)
        if 0 < len(repo.index.diff(repo.head.commit)):
            repo.index.commit("S3 updated", author=actor, committer=actor)
            repo.remote().push()
        shutil.rmtree(repo_path)
        return json.dumps({ "success": True, "message": "Done witout error!" })
    except Exception as e:
        err = "\n".join(traceback.format_exception(e))
        print(err)
        raise(e)
