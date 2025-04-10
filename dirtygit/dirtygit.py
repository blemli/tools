#!/usr/bin/env python3

import os, click
from shell import shell
from tqdm import tqdm
from concurrent.futures import ThreadPoolExecutor

@click.command()
@click.argument("location", default=".")
@click.option("--behind", is_flag=True, help="Check if the repo is behind the upstream")
def dirtygit(location=".", behind=False):
    dirs = [d for d in os.scandir(os.path.expanduser(location)) if os.path.isdir(d.path)] #todo: recurse but only if not already a git folder
    repos = [d for d in dirs if os.path.exists(os.path.join(d.path, ".git"))]
    def check_repo(repo):
        is_dirty = shell(f"git -C {repo.path} status --porcelain").output()
        is_ahead = shell(f"git -C {repo.path} log --oneline @{{u}}..HEAD").output()
        is_behind = False
        if behind:
            shell(f"git -C {repo.path} fetch")
            is_behind = shell(f"git -C {repo.path} log --oneline HEAD..@{{u}}").output()
        if is_dirty or is_ahead or is_behind:
            return repo
        return None
    with ThreadPoolExecutor() as executor:
        results = list(tqdm(executor.map(check_repo, repos), total=len(repos)))
    dirty_repos = [repo for repo in results if repo]
    for repo in dirty_repos:
        print(repo.name)
    return dirty_repos

if __name__ == "__main__":
    dirtygit()
