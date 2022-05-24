import os
from os import environ
import shutil
import datetime as dt
import json
import sys
import re
import glob
import urllib

import requests
from dotenv import load_dotenv
from pprint import pprint
from notion2md.exporter.block import MarkdownExporter
from git import Repo
from PIL import Image


load_dotenv()
hugo_branch = 'source'
endpoint = 'https://api.notion.com/v1/{0}'
api_headers = {'Authorization': 'Bearer {0}'.format(environ.get('INPUT_NOTION_API_TOKEN')),
                'Content-Type': 'application/json',
                'Notion-Version': '2022-02-22'}
blog_db_id = environ.get('INPUT_BLOG_DB_ID')

os.environ['GIT_USERNAME'] = environ.get('INPUT_GITHUB_USER')
os.environ['GIT_PASSWORD'] = environ.get('INPUT_GITHUB_TOKEN')
os.environ['NOTION_TOKEN'] = environ.get('INPUT_NOTION_API_TOKEN')


def str_to_timestamp(iso_string):
    return dt.datetime.fromisoformat(iso_string.replace('Z', '+00:00')).timestamp()

def timestamp_to_str(timestamp):
    return str(dt.datetime.fromtimestamp(timestamp, dt.timezone.utc)).replace(' ', 'T')

def get_metadata(edited_at):
    data = {
        'filter': {
            'and': [
                {
                    'property': 'Updated',
                    'last_edited_time': {
                        'after': edited_at
                    }
                },
                {
                    'property': 'Publish',
                    'checkbox': {
                        'equals': True
                    }
                }
            ]
        },
        'sorts': [
            {
                'property': 'Updated',
                'direction': 'ascending'
            }
        ]
    }
    r = requests.request('POST', url=endpoint.format('databases/' + blog_db_id + '/query'),
                           data=json.dumps(data), headers=api_headers)
    metadata = []
    for result in r.json()['results']:
        # pprint(result)
        created_timestamp = str_to_timestamp(result['created_time'])
        created_datetime = dt.datetime.fromtimestamp(created_timestamp, dt.timezone(dt.timedelta(hours=9), 'Asia/Tokyo'))
        metadata.append({
            'id': result['id'],
            'created_at': {
                'string': created_datetime.strftime('%Y-%m-%dT%H:%M:%S%z_').replace('00_', ':00'),
                'timestamp': created_timestamp
            },
            'edited_at': str_to_timestamp(result['last_edited_time']),
            'title': result['properties']['Title']['title'][0]['plain_text'],
            'description': result['properties']['Description']['rich_text'][0]['plain_text'],
            'path': result['properties']['Path']['rich_text'][0]['plain_text'],
            'url': result['url'],
            'image': result['properties']['OGPImage']['files'][0]['file']['url'],
            'tags': [x['name'] for x in result['properties']['Tags']['multi_select']],
            'series': [x['name'] for x in result['properties']['Series']['multi_select']],
            'archives': created_datetime.strftime('%Y-%m'),
            'draft': False
        })
    return metadata


if __name__ == '__main__':
    # 実行時間削減のため、更新が必要なときだけ git clone する
    # GitHub API から最新コミットを取得
    res = requests.request('GET', 'https://api.github.com/repos/tbsmcd/tbsmcd.github.io/branches/source')
    commited_at = res.json()['commit']['commit']['author']['date'].replace('Z', '+00:00')

    # Notion API から最新コミット以降の更新を検索
    pages = get_metadata(commited_at)
    if len(pages) == 0:
        print('No new articles found')
        sys.exit(0)

    # git clone && checkout
    load_dotenv()
    local_repo = os.path.dirname(__file__) + '/github/hugo'
    if os.path.exists(local_repo):
        shutil.rmtree(local_repo)
    remote_repo = 'https://{}:{}@github.com/tbsmcd/tbsmcd.github.io.git'\
        .format(environ.get('INPUT_GITHUB_USER'), environ.get('INPUT_GITHUB_TOKEN'))
    Repo.clone_from(remote_repo, local_repo)
    repo = Repo(local_repo)
    repo.git.checkout('source')

    repo.config_writer().set_value('user', 'name', environ.get('INPUT_GITHUB_USERNAME')).release()
    repo.config_writer().set_value('user', 'email', environ.get('INPUT_GITHUB_EMAIL')).release()

    # notion2md で markdown を取得する
    # OGP image も取得してしまう
    notion_base = os.path.dirname(__file__) + '/notion'
    for file in os.listdir(notion_base):
        if os.path.isdir(os.path.join(notion_base, file)):
            shutil.rmtree(os.path.join(notion_base, file))
    for page in pages:
        print('Page: {}'.format(page['title']))
        dl_path = os.path.join(notion_base, page['id'])
        MarkdownExporter(block_id=page['id'].replace('-', ''),
                         output_path=dl_path,
                         download=True).export()

        # zip ファイルが存在したら展開して削除
        zip_files = glob.glob(os.path.join(dl_path, '*.zip'))
        if len(zip_files) == 1:
            shutil.unpack_archive(zip_files[0], dl_path)
            os.remove(zip_files[0])

        # OGP ダウンロード
        if len(page['image']) != 0:
            file_name = re.sub('\?.*$', '', page['image']).split('/')[-1]
            ext = file_name.split('.')[-1]
            url_data = requests.get(page['image']).content
            with open(os.path.join(notion_base, page['id'], 'ogp.' + ext) ,mode='wb') as f: # wb でバイト型を書き込める
                f.write(url_data)
                page['ogp_filename'] = 'ogp.' + ext

        # ディレクトリ内の画像を最大幅800にリサイズする
        for f in glob.glob(os.path.join(notion_base, page['id'], '*')):
            if re.search(r'\.(bmp|gif|png|jpeg|jpg|tiff|tif|webp)$', f, re.IGNORECASE):
                im = Image.open(f)
                w, h = im.size
                if w > 800:
                    height = round(h * 800/w)
                    resized = im.resize((800, height), resample=Image.LANCZOS)
                    resized.save(f)

        # メタ情報を整理
        meta_rows = [
            'title: "{}"'.format(page['title']),
            'description: "{}"'.format(page['description']),
            'date: "{}"'.format(page['created_at']['string']),
            'tags: [{}]'.format(', '.join(['"{}"'.format(x) for x in page['tags']])),
            'series: [{}]'.format(', '.join(['"{}"'.format(x) for x in page['series']])),
            'archives: "{}"'.format(page['archives']),
                     ]
        if 'ogp_filename' in page:
            meta_rows.append('image: "{}"'.format(page['ogp_filename']))
        header = '---\n{}\n---\n\n\n'.format('\n'.join(meta_rows))

        # Markdown を編集・修正
        markdown_file = os.path.join(notion_base, page['id'], page['id'].replace('-', '') + '.md')
        with open(markdown_file, mode='r') as f:
            md = f.read()
        # list 表示に余計な空白が入る箇所を修正
        md = re.sub(r'^-  .+', '- ', md, flags=(re.MULTILINE | re.DOTALL))
        md_lines = md.splitlines()
        i = -1
        fix_list = []
        for li in md_lines:
            i += 1
            if len(li) == 0 and i > 0 and len(md_lines) > i + 1:
                if md_lines[i - 1].strip().startswith('- ') and md_lines[i + 1].strip().startswith('- '):
                    continue
            fix_list.append(li)
        md = '\n'.join(fix_list)

        # シリーズを追加
        series = ''
        if len(page['series']) > 0:
            series = series + '\n'
        for s in page['series']:
            series = series + '{{< series name="' + s +'">}}\n'

        # メタ情報を Markdown と組み合わせ index.md を作成する
        with open(os.path.join(notion_base, page['id'], 'index.md'), mode='w') as f:
            f.write(header + series + md)
        os.remove(markdown_file)

        # ファイルを hugo 用リポジトリに追加する
        if len(page['path']) == 0:
            page['path'] = page['id']

        new_post = os.path.join(local_repo, 'content/post', page['path']) + '/'
        if os.path.exists(new_post):
            shutil.rmtree(new_post)
        shutil.move(os.path.join(notion_base, page['id']) + '/',
                    new_post)

        # git commit
        repo.git.add(os.path.join('content/post', page['path']))
        repo.git.commit(os.path.join('content/post', page['path']), '-m', '\"Added page: {}\"'.format(page['title']))
    repo.git.push('origin', 'source:source')
