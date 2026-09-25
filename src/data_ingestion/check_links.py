import urllib.request
import re
year = "2026"
month = "08_Aug" # We are in Sept 2026, let's check Aug
url = f'https://noaadata.apps.nsidc.org/NOAA/G02135/south/daily/geotiff/{year}/{month}/'
try:
    html = urllib.request.urlopen(url).read().decode('utf-8')
    links = re.findall(r'href="([^"]+\.tif)"', html)
    print(f"Found {len(links)} tif files in {year}/{month}")
    if links:
        print("Last 5 files:", links[-5:])
except Exception as e:
    print(f"Error accessing {url}:", e)
