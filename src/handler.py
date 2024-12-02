import os
import shutil
import json
import traceback
import hashlib
import glob
from concurrent.futures import ThreadPoolExecutor, Future
import subprocess
import git
import boto3
from dotenv import load_dotenv
from boto3_type_annotations.s3 import ServiceResource
from boto3_type_annotations.s3.service_resource import ObjectSummary
from aws_lambda_typing import events, context

import time

DOTENV = ".env.s3git"

s3: ServiceResource = boto3.resource("s3")

tmp_base = os.path.join("/tmp", str(time.time()))
os.makedirs(tmp_base)
repo_path = os.path.join(tmp_base, "repo")
def git_run(args: list[str], cwd=repo_path):
    cmd = ["git"]
    cmd.extend(args)
    return subprocess.run(cmd, cwd=cwd)

def clone(origin: str) -> git.Repo:
    return git.Repo.clone_from(origin, repo_path, multi_options=["--depth=1"])

def hash_diff(etag: str, file_path: str):
    try:
        with open(file_path, "rb") as f:
            file_hash = hashlib.md5(f.read())
        return etag != file_hash
    except FileNotFoundError:
        return True

def handler(event: events.S3Event, context: context.Context):
    try:
        buckets = set(
            map(
                lambda x: x["s3"]["bucket"]["name"],
                filter(
                    lambda x: x["eventName"].startswith("ObjectCreated") or x["eventName"].startswith("ObjectRemoved"),
                    event["Records"]
                )
            )
        )
        for bucket_name in buckets:
            bucket = s3.Bucket(bucket_name)
            env_file = os.path.join(tmp_base, ".env")
            bucket.download_file(DOTENV, env_file)
            load_dotenv(env_file)

            start = time.time()

            # setup repository
            if os.path.isdir(repo_path):
                shutil.rmtree(repo_path)
            repo = clone(os.environ["GIT_ORIGIN"])
            repo.config_writer().set_value("http", "postBuffer", "50M")

            author = git.Actor(os.environ["USERNAME"], os.environ["EMAIL"])
            #if clone().returncode != 0:
            #    raise Exception("clone error")
            print("clone @", time.time() - start)

            # get files in repo
            to_delete = glob.glob("**/*", root_dir=repo_path, recursive=True, include_hidden=True)
            to_delete = list(filter(lambda x: os.path.isfile(os.path.join(repo_path, x)), to_delete))

            # get bucket info
            objects: list[ObjectSummary] = list(bucket.objects.all())
            print("list object @", time.time() - start)

            thread_sent: list[Future[None]] = []

            # thread for MD5 calculation
            with ThreadPoolExecutor() as thread:
                for i, objsum in enumerate(objects):
                    key = objsum.key
                    try:
                        to_delete.remove(key)
                    except:
                        pass
                    if 10000000 < objsum.size:
                        continue

                    # check in new thread
                    def check(etag: str, key: str):
                        def f():
                            path = os.path.join(repo_path, key)
                            if repo.ignored(path):
                                return
                            os.makedirs(os.path.dirname(path), exist_ok=True)
                            try:
                                with open(path, "rb") as f:
                                    file_hash = hashlib.md5(f.read()).hexdigest()
                                if etag == f"\"{file_hash}\"":
                                    return
                            except FileNotFoundError:
                                pass
                            print("updated", key)
                            bucket.download_file(key, path)
                        return f
                    # copy str for multithreading
                    thread_sent.append(thread.submit(check(f"{objsum.e_tag}", f"{key}")))
                    print("task sent:", f"{i}/{len(objects)}")

                # join threads
                list(map(lambda x: x.result(), thread_sent))
                print("all joined @", time.time() - start)

            # list to delete
            for delete in to_delete:
                if not delete.startswith(".") or delete.startswith(".obsidian/"):
                    print("delete", delete)
                    path = os.path.join(repo_path, delete)
                    os.remove(path)

            repo.git.add(A=True)
            diff = list(repo.index.diff(repo.head.commit))
            if len(diff) != 0:
                print("diff: ", len(diff))
                repo.index.commit("S3 updated", author=author, committer=author)
                repo.remote().push().raise_if_error()
                print("pushed @", time.time() - start)
            else:
                print("none to push")
            shutil.rmtree(repo_path)

        print("Done without error!")
        return json.dumps({ "success": True, "message": "Done witout error!" })
    except Exception as e:
        err = "\n".join(traceback.format_exception(e))
        print(err)
        raise(e)
