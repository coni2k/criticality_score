# Copyright 2020 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Main python script for calculating OSS Criticality Score."""

import argparse
import csv
import datetime
import logging
import os
import time

from .constants import *  # pylint: disable=wildcard-import
from . import run

logger = logging.getLogger()

LANGUAGE_SEARCH_MAP = {
    'c': ['C'],
    'c#': ['C#'],
    'c++': ['C++'],
    'go': ['Go'],
    'java': ['Java', 'Groovy', 'Kotlin', 'Scala'],
    'js': ['Javascript', 'Typescript', 'CoffeeScript'],
    'php': ['PHP'],
    'python': ['Python'],
    'ruby': ['Ruby'],
    'rust': ['Rust'],
    'shell': ['Shell'],
}
IGNORED_KEYWORDS = ['docs', 'interview', 'tutorial']

def get_github_repo_urls(sample_size, languages):
    urls = []
    if languages:
        for lang in languages:
            lang = lang.lower()
            for github_lang in LANGUAGE_SEARCH_MAP.get(lang, lang):
                urls = get_github_repo_urls_for_language(urls, sample_size, github_lang)
    else:
        urls = get_github_repo_urls_for_language(urls, sample_size)

    return urls


def get_github_repo_urls_for_language(urls, sample_size, github_lang=None):
    """Return repository urls given a language list and sample size."""
    upper_limit = 409
    samples_processed = 1
    while samples_processed <= sample_size:
        query = get_github_query(github_lang, upper_limit)
        token_obj = run.get_github_auth_token()
        new_result = False
        for repo in token_obj.search_repositories(query=query,
                                                    sort='stars',
                                                    order='desc'):
            # Forced sleep to avoid hitting rate limit.
            time.sleep(0.1)
            repo_url = repo.html_url
            if repo_url in urls:
                # Github search can return duplicates, so skip if analyzed.
                continue
            if any(k in repo_url.lower() for k in IGNORED_KEYWORDS):
                # Ignore uninteresting repositories.
                continue
            urls.append(repo_url)
            new_result = True
            logger.info(f'{samples_processed} - {repo.name} - {repo_url} - {repo.stargazers_count}')
            samples_processed += 1
            if samples_processed > sample_size:
                break
        if not new_result:
            break
        upper_limit = repo.stargazers_count

        # TODO last_stars_processed = repo.stargazers_count
        stars_upper = repo.stargazers_count + 10
        stars_lower = repo.stargazers_count - 500
    
    return urls

def get_github_query(github_lang=None, upper_limit=None):
    query = 'archived:false'
    if github_lang:
        query += f' language:{github_lang}'
    query += f' stars:>{GITHUB_QUERY_LOWER_LIMIT}' if not upper_limit else f' stars:{GITHUB_QUERY_LOWER_LIMIT}..{upper_limit}'
    logger.info(f'GitHub query: {query}')
    return query


def get_github_query_upper_limit(github_lang=None):
    query = get_github_query(github_lang)
    token_obj = run.get_github_auth_token()
    for repo in token_obj.search_repositories(query=query,
                                                sort='stars',
                                                order='desc'):
        return repo.stargazers_count


def initialize_logging_handlers(output_dir):
    log_filename = os.path.join(output_dir, 'output.log')
    logging.basicConfig(filename=log_filename, filemode='w', level=logging.INFO)

    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    logging.getLogger('').addHandler(console)

def main():
    start_time = datetime.datetime.now()
    print(start_time)

    parser = argparse.ArgumentParser(
        description=
        'Generate a sorted criticality score list for particular language(s).')
    parser.add_argument("--language",
                        nargs='+',
                        default=[],
                        required=False,
                        choices=LANGUAGE_SEARCH_MAP.keys(),
                        help="List of languages to use.")
    parser.add_argument("--output-dir",
                        type=str,
                        required=True,
                        help="Directory to place the output in.")
    parser.add_argument("--count",
                        type=int,
                        default=200,
                        help="Number of projects in result.")
    parser.add_argument("--sample-size",
                        type=int,
                        default=5000,
                        help="Number of projects to analyze (in descending order of stars).")

    args = parser.parse_args()

    initialize_logging_handlers(args.output_dir)

    # GitHub search can return incomplete results in a query, so try it multiple
    # times to avoid missing urls.
    repo_urls = set()
    logger.info(f'\r\nFinding repos...')
    repo_urls.update(get_github_repo_urls(args.sample_size, args.language))

    if len(repo_urls) == 0:
        logger.info('No repo found with given parameters')
        return

    stats = []
    index = 1
    output = None
    logger.info(f'\r\nProcessing repos...')
    for repo_url in repo_urls:
        for _ in range(3):
            try:
                repo = run.get_repository(repo_url)
                if not repo:
                    logger.error(f'Repo not found: {repo_url}')
                    break
                output = run.get_repository_stats(repo)
                break
            except Exception as exp:
                logger.exception(f'Exception occurred when reading repo: {repo_url}\n{exp}')
        if not output:
            continue
        logger.info(f"{index} - {output['name']} - {output['url']} - {output['criticality_score']}")
        stats.append(output)
        index += 1

    languages = '_'.join(args.language) if args.language else 'all'
    languages = languages.replace('+', 'plus').replace('c#', 'csharp')
    output_filename = os.path.join(args.output_dir,
                                   f'{languages}_top_{args.count}.csv')
    with open(output_filename, 'w') as file_handle:
        csv_writer = csv.writer(file_handle)
        header = output.keys()
        csv_writer.writerow(header)
        for i in sorted(stats,
                        key=lambda i: i['criticality_score'],
                        reverse=True)[:args.count]:
            csv_writer.writerow(i.values())
    logger.info(f'\r\nWrote results: {output_filename}')

    end_time = datetime.datetime.now()
    print(end_time)
    diff = (end_time - start_time).total_seconds() / 60.0
    print(diff)
    


if __name__ == "__main__":
    main()
