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


def unicode_escape(escaped):
    return escaped.encode().decode('unicode_escape')


def exec_js(js_data):
    p = subprocess.Popen(['node'], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    stdout, stderr = p.communicate(js_data)
    print(stdout)


class Browser(object):

    def __init__(self):
        self.sf_response = None
        self.headers = self.get_headers()
        self.session = requests.Session()

    def get_headers(self):
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                          "Chrome/87.0.4280.88 Safari/537.36"
        }
        return self.headers

    def send_request(self, method, url, **kwargs):
        sf_response = self.session.request(method, url, **kwargs)
        if sf_response.status_code == 200:
            return sf_response
        return None


class SaveFromApi(Browser):

    def __init__(self):
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
        for tag in streaming_data['adaptiveFormats']:
            stream_dict = {}
            stream_dict['title'] = video_details['title']
            if not tag.get('signatureCipher'):
                stream_dict['url'] = tag['url']
                if tag.get("mimeType").split(';')[0] == 'video/webm':
                    stream_dict['resolution'] = f'{tag.get("width")}x{tag.get("height")} {tag.get("qualityLabel")}'
                    stream_dict['quality'] = tag.get('quality')
                    streaming_list[0]['video'].append(stream_dict)
                elif tag.get("mimeType").split(';')[0] == 'audio/webm':
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
                stream_dict['url'] = get_info_video['converter']['mp4']['720p']['stream'][1]['url']
                stream_dict['quality'] = get_info_video['converter']['mp4']['720p']['stream'][1]['format']
                streaming_list[1]['audio'].append(stream_dict)
                return streaming_list
        return streaming_list

    def downloader(self, url, file_path='', attempts=2):
        url = requests.utils.unquote(url)
        if not file_path:
            file_path = os.path.realpath(os.path.basename(url))
        print(f'Baixando {requests.utils.unquote(url).replace("%2C", ",").replace("%2F", "/").replace("%3D", "=")} '
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
                    with open(file_path, 'wb') as out_file, tqdm(
                            desc=file_path,
                            total=total,
                            unit='iB',
                            unit_scale=True,
                            unit_divisor=1024,
                    ) as bar:
                        for chunk in self.response.iter_content(chunk_size=1024 * 1024):
                            size = out_file.write(chunk)
                            bar.update(size)
                    print('Arquivo baixado com sucesso')
                    return file_path
            except Exception as ex:
                print(f'Tentativa #{attempt} falhou com erro: {ex}')
        return ''


if __name__ == '__main__':
    yt_id = input('Digite a url do vídeo que deseja baixar: ').split('v=')[1]
    ytd = YouTubeDownloader()
    response = ytd.get_response(yt_id)
    data = ytd.get_data()
    streams = ytd.get_streams_data()
    # print(streams)
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
            if content_type == 'video':
                print(f'{index + 1} ==> {stream["resolution"]}')
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
            ytd.downloader(url_download, file_path=title_video)
    else:
        print('Nenhum item encontrado para a opção desejada.')
