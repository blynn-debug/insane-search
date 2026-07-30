from curl_cffi import requests as r
ck = open(r"C:\Users\user\PycharmProjects\insane-search\existing\reference\tank_auction\cookies.txt").read().strip()
s = r.Session(impersonate="chrome")
s.headers.update({"Cookie": ck, "Referer":"https://www.tankauction.com/ca/caList.php"})
# warm
try:
    w = s.get("https://tankauction.com/ca/caList.php?page=1", timeout=20)
    print("warm", w.status_code, len(w.text))
except Exception as e:
    print("warm err", e)
# NEW list API - test sold in 인천(siCd=28), 대지 category
url="https://tankauction.com/api/proxy/api1.php/ca/AuctList.php?dataSize=5&pageNo=1&stat=1210"
try:
    x = s.get(url, timeout=20)
    print("api", x.status_code, x.text[:400])
except Exception as e:
    print("api err", e)
