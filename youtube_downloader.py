# -*- coding: utf-8 -*-
# Agradecimentos a Eritque arcus pelo método Save From que possibilita assim o download de vídeos privados
# https://stackoverflow.com/questions/65443895/how-to-input-data-via-a-post-request-using-requests-in-python
# https://github.com/Nambers/YoutubeDownloader/blob/main/Youtube.py

# Método Save From requer node instalado, bem como a lib node jsdom, em sistemas Linux fez-se necessário a edição
# do arquivo "/node_modules/whatwg-url/dist/encoding.js" comentando a seguinte instrução
# //const utf8Decoder = new TextDecoder("utf-8", { ignoreBOM: true });

import os
import re
import sys
import json
import time
import execjs
import requests
import subprocess
from tqdm import tqdm

URL_BASE = 'https://www.youtube.com'
URL_SAVE_FROM = 'https://worker.sf-tools.com'
UNITS_MAPPING = [
    (1 << 50, ' PB'),
    (1 << 40, ' TB'),
    (1 << 30, ' GB'),
    (1 << 20, ' MB'),
    (1 << 10, ' KB'),
    (1, (' byte', ' bytes')),
]


def unicode_escape(escaped):
    return escaped.encode().decode('unicode_escape')


def pretty_size(value, units=None):
    global factor, suffix
    if units is None:
        units = UNITS_MAPPING
    for factor, suffix in units:
        if value >= factor:
            break
    amount = int(value / factor)

    if isinstance(suffix, tuple):
        singular, multiple = suffix
        if amount == 1:
            suffix = singular
        else:
            suffix = multiple
    return str(amount) + suffix


def exec_js(js_data):
    p = subprocess.Popen(['node'], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    stdout, stderr = p.communicate(js_data)
    print(stdout)


class Browser(object):

    def __init__(self):
        self.response = None
        self.headers = self.get_headers()
        self.session = requests.Session()

    def get_headers(self):
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                          "Chrome/87.0.4280.88 Safari/537.36"
        }
        return self.headers

    def send_request(self, method, url, **kwargs):
        self.response = self.session.request(method, url, **kwargs)
        if self.response.status_code == 200:
            return self.response
        return None


class SaveFromApi(Browser):

    def __init__(self):
        self.sf_response = None
        super().__init__()

    def get_response(self, video_id):
        self.headers['referer'] = 'https://pt.savefrom.net/15/'
        sf_data = {
            'sf_url': f'https://www.youtube.com/watch?v={video_id}',
            'sf_submit': '',
            'new': 2,
            'lang': 'pt',
            'app': '',
            'country': 'br',
            'os': 'Linux',
            'browser': 'Chrome',
            'channel': 'main',
            'sf-nomad': 1
        }

        self.sf_response = self.send_request('POST', f'{URL_SAVE_FROM}/savefrom.php', data=sf_data,
                                             headers=self.headers)

        fake_dom = """
            if (typeof TextEncoder === 'undefined') { 
                const { TextEncoder } = require('util');
                this.global.TextEncoder = TextEncoder; 
            } 
            const jsdom = require("jsdom");
            const { JSDOM } = jsdom;
            const dom = new JSDOM(`<!DOCTYPE html><p>Hello world</p>`);
            window = dom.window;
            document = window.document;
            XMLHttpRequest = window.XMLHttpRequest;
        """

        js = self.sf_response.text.replace("(function(){",
                                           "(function(){\nthis.alert=function(){};").replace("/*js-response*/", "")

        encrypted_js = js.split("\n")
        decrypt_fun = encrypted_js[len(encrypted_js) - 3].split(";")[0] + ";"
        new_js = fake_dom + js
        ct = execjs.compile(new_js)
        js_string = decrypt_fun.replace(";", "")

        if "=" in decrypt_fun:
            js_string = decrypt_fun.split("=")[1].replace(";", "")
        else:
            js_string = js_string.split(',')[-1:][0].replace('))', ')').replace(']', '')

        decrypted_js = ct.eval(js_string)
        result = re.compile(r'show\((.*?)\);;').findall(decrypted_js)[0]
        result_data = json.loads(result)
        json_data = json.dumps(result_data, indent=4)
        # print(json_data)

        if result_data:
            return result_data
        return False


class YouTubeDownloader(Browser):

    def __init__(self):
        self.response = None
        self.result_data = None
        self.video_id = None
        self.file_path = None
        super().__init__()

    def get_response(self, video_id):
        self.video_id = video_id
        yt_data = {
            'v': self.video_id
        }
        self.response = self.send_request('GET', f'{URL_BASE}/watch', params=yt_data, headers=self.headers)
        if self.response:
            return self.response.text
        return False

    def get_data(self):
        match = re.compile(r'var ytInitialPlayerResponse = (.*?);var').findall(self.response.text)[0]
        self.result_data = json.loads(match)
        # print(json.dumps(self.result_data, indent=4))
        return self.result_data

    def get_streams_data(self):
        streaming_data = self.result_data['streamingData']
        video_details = self.result_data['videoDetails']
        streaming_list = [
            {
                "video": [],
            },
            {
                "audio": [],
            }
        ]
        # print(json.dumps(streaming_data, indent=4))
        if streaming_data.get("hlsManifestUrl"):
            stream_dict = {}
            stream_dict['title'] = video_details['title']
            stream_dict['url'] = streaming_data["hlsManifestUrl"]
            stream_dict['resolution'] = "1080"
            stream_dict['quality'] = "HD"
            stream_dict['live'] = True
            streaming_list[0]['video'].append(stream_dict)
        for value in ['formats', 'adaptiveFormats']:
            for tag in streaming_data.get(value) if streaming_data.get(value) else []:
                stream_dict = {}
                stream_dict['title'] = video_details['title']
                if not tag.get('signatureCipher'):
                    stream_dict['url'] = tag['url']
                    mimetype = tag.get("mimeType").split(';')[0]
                    if mimetype.split('/')[0] == 'video':
                        size_file = f'{mimetype.split("/")[1]} ' \
                                    f'{pretty_size(int(tag.get("contentLength"))) if tag.get("contentLength") else ""}'
                        stream_dict['resolution'] = f'{tag.get("width")}x{tag.get("height")} ' \
                                                    f'{tag.get("qualityLabel")} {size_file}'
                        stream_dict['quality'] = tag.get('quality')
                        streaming_list[0]['video'].append(stream_dict)
                    elif tag.get("mimeType").split(';')[0].split('/')[0] == 'audio':
                        stream_dict['quality'] = tag.get('audioQuality')
                        streaming_list[1]['audio'].append(stream_dict)
                else:
                    # stream_dict['url'] = re.compile(r'url=(.*?)$').findall(tag['signatureCipher'])[0]
                    sfa = SaveFromApi()
                    get_info_video = sfa.get_response(self.video_id)
                    for url in get_info_video["url"]:
                        stream_dict = {}
                        stream_dict['title'] = video_details['title']
                        if not url.get('no_audio') and url.get('info_token'):
                            stream_dict['url'] = url["url"]
                            stream_dict['resolution'] = url["quality"]
                            stream_dict['quality'] = url["quality"]
                            streaming_list[0]['video'].append(stream_dict)
                    if get_info_video.get('converter'):
                        stream_dict['url'] = get_info_video['converter']['mp4']['720p']['stream'][1]['url']
                        stream_dict['quality'] = get_info_video['converter']['mp4']['720p']['stream'][1]['format']
                        streaming_list[1]['audio'].append(stream_dict)
                    return streaming_list
        return streaming_list

    def downloader(self, url, file_path='', attempts=2):
        url = requests.utils.unquote(url).replace("%2C", ",").replace("%2F", "/").replace("%3D", "=")
        if not file_path:
            file_path = os.path.realpath(os.path.basename(url))
        self.file_path = file_path.replace('/', '').replace(' ', '_')
        print(f'Baixando {url} '
              f'conteúdo para {file_path}')
        url_sections = requests.utils.urlparse(url)
        if not url_sections.scheme:
            print('Falta um protocolo no url fornecido. Adicionando protocolo http...')
            url = f'http://{url}'
            print(f'Nova url: {url}')
        for attempt in range(1, attempts + 1):
            try:
                if attempt > 1:
                    time.sleep(10)
                with self.send_request('GET', url, headers=self.headers, stream=True) as self.response:
                    self.response.raise_for_status()
                    total = int(self.response.headers.get('content-length', 0))
                    with open(self.file_path, 'wb') as out_file, tqdm(
                            desc=self.file_path,
                            total=total,
                            unit='iB',
                            unit_scale=True,
                            unit_divisor=1024 * 1024,
                    ) as bar:
                        for chunk in self.response.iter_content(chunk_size=1024 * 1024):
                            size = out_file.write(chunk)
                            bar.update(size)
                    print('Arquivo baixado com sucesso')
                    return self.file_path
            except Exception as ex:
                print(f'Tentativa #{attempt} falhou com erro: {ex}')
        return ''

    def search(self, query_search):
        encoded_search = requests.utils.quote(query_search)
        search_data = {
            'search_query': encoded_search,
        }
        self.response = self.send_request('GET', f'{URL_BASE}/results', params=search_data, headers=self.headers)
        if self.response:
            return self.parse_js()
        return False

    def parse_js(self):
        results = []
        match = re.compile(r'var ytInitialData = (.*?);</script>').findall(self.response.text)[0]
        video_results = json.loads(match)
        primary_contents = video_results["contents"]["twoColumnSearchResultsRenderer"]["primaryContents"]
        contents = primary_contents["sectionListRenderer"]["contents"][0]["itemSectionRenderer"]["contents"]
        try:
            items = contents[0]["shelfRenderer"]["content"]["verticalListRenderer"]["items"]
        except:
            items = contents
        for item in items:
            try:
                video_info = item["videoRenderer"]
                video_info = {
                    "title": video_info["title"]["runs"][0]["text"],
                    "link": URL_BASE + video_info["navigationEndpoint"]["commandMetadata"]["webCommandMetadata"]["url"],
                    "id": video_info["navigationEndpoint"]["commandMetadata"]["webCommandMetadata"]["url"].split('=')[1]
                }
                results.append(video_info)
            except KeyError:
                pass
        return results

    def play(self):
        os.system(f"cvlc {self.file_path}")


if __name__ == '__main__':
    ytd = YouTubeDownloader()
    yt_id = None
    list_videos = []
    yt_action = input('Faça uma busca por vídeos ou digite a url do vídeo que deseja baixar: ')
    if yt_action.startswith('https://'):
        yt_id = yt_action.split('v=')[1]
    else:
        list_videos = ytd.search(yt_action)
    if len(list_videos) > 0:
        for index, stream in enumerate(list_videos):
            print(f'{index} ==> {stream["title"]}')
        try:
            selected_video = int(input(f'Digite o número correspondente ao vídeo: '))
        except:
            sys.exit()
        yt_id = list_videos[selected_video]['id']
    response = ytd.get_response(yt_id)
    data = ytd.get_data()
    streams = ytd.get_streams_data()
    try:
        options = int(input('Digite 1 para baixar vídeos ou 2 para áudios: '))
    except:
        sys.exit()
    mode = 'resolução'
    extension = 'mp4'
    content_type = 'video'
    content_index = 0
    if options == 2:
        mode = 'qualidade de som'
        extension = 'mp3'
        content_type = 'audio'
        content_index = 1
    if len(streams[content_index][content_type]) > 0:
        for index, stream in enumerate(streams[content_index][content_type]):
            extension = 'm3u8' if stream.get("live") else extension
            if content_type == 'video':
                print(f'{index + 1} ==> {stream["resolution"]} {"HD Ao Vivo" if stream.get("live") else ""}')
            else:
                print(f'{index + 1} ==> mp3 {stream["quality"]}')
        try:
            stream_selected = 1
            if len(streams[content_index][content_type]) > 1:
                stream_selected = int(input(f'Digite o número correspondente a {mode} desejada: '))
        except:
            sys.exit()
        if stream_selected <= len(streams[content_index][content_type]):
            # print(streams[content_index][content_type][stream_selected - 1])
            url_download = streams[content_index][content_type][stream_selected - 1]['url']
            title_video = f"{streams[content_index][content_type][stream_selected - 1]['title']}.{extension}"
            download = ytd.downloader(url_download, file_path=title_video)
            if download:
                ytd.play()
    else:
        print('Nenhum item encontrado para a opção desejada.')

    exit(0)
