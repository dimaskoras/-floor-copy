import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from mpunav import catalog, fetch_map, map_bytes


class MapCacheTests(unittest.TestCase):
    def test_verified_cached_map_opens_without_network(self):
        raw=b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 100"><script>bad()</script><path d="M0 0L10 10"/></svg>'
        with tempfile.TemporaryDirectory() as folder:
            data=Path(folder);cache=data/'mpunav';(cache/'maps').mkdir(parents=True)
            (cache/'maps'/'PK-MAIN-5.svg').write_bytes(raw)
            (cache/'manifest.json').write_text(json.dumps({'plans':{'PK-MAIN-5.svg':{'size':len(raw),'hash':'sha256-'+hashlib.sha256(raw).hexdigest()}}}))
            with patch('urllib.request.urlopen',side_effect=AssertionError('Network must not be used')):
                self.assertTrue(catalog(data)[0]['cached'])
                mapping=fetch_map('PK-MAIN-5.svg',data,data/'project')
            self.assertEqual(mapping['viewBox'],[0,0,200,100])
            self.assertNotIn('<script',(data/'project'/'mpunav.svg').read_text())

    def test_unverified_download_is_not_cached(self):
        with tempfile.TemporaryDirectory() as folder:
            item={'name':'A-0.svg','size':3,'hash':'sha256-'+'0'*64}
            with patch('urllib.request.urlopen') as opened:
                opened.return_value.__enter__.return_value.read.return_value=b'bad'
                with self.assertRaisesRegex(ValueError,'SHA-256'):map_bytes(item,folder)
            self.assertFalse((Path(folder)/'mpunav/maps/A-0.svg').exists())
