from pathlib import Path
import urllib.request


def install():
    folder=Path(__file__).resolve().parent/'web/fonts';folder.mkdir(exist_ok=True)
    for name in ['Regular','Medium','Semibold','Bold']:
        destination=folder/f'Gilroy-{name}.woff2'
        if not destination.exists():
            url=f'https://mpunav.ru/fonts/gilroy/Gilroy-{name}.woff2'
            with urllib.request.urlopen(url,timeout=20) as response:raw=response.read()
            if not raw.startswith(b'wOF2'):raise ValueError('Ответ сайта не является WOFF2')
            destination.write_bytes(raw)


if __name__=='__main__':install()
