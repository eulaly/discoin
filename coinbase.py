from os import getenv
import json, hmac, hashlib, time, requests
from requests.auth import AuthBase

cb_key = getenv("cb_key")
cb_secret = getenv("cb_secret")

class CoinbaseWalletAuth(AuthBase):
    def __init__(self, cb_key, cb_secret):
        self.key = cb_key
        self.secret = cb_secret

    def __call__(self,request):
        timestamp = str(int(time.time()))
        message = timestamp + request.method + request.path_url + (request.body or '')
        signature = hmac.new(self.key.encode(), message.encode(), hashlib.sha256).hexdigest()
        request.headers.update({
            'CB-ACCESS-SIGN': signature,
            'CB-ACCESS-TIMESTAMP': timestamp,
            'CB-ACCESS-KEY': self.key,
            'content-type': 'application/json',
        })
        return request

cb_baseurl = 'https://api.coinbase.com/v2/'
cb_auth = CoinbaseWalletAuth(cb_key=cb_key,cb_secret=cb_secret)

def coinbase_time():
    headers = {'content-type': 'application/json'}
    time_url = 'https://api.coinbase.com/v2/time'
    r = requests.get(time_url, headers=headers)
    if r.status_code == 200:
        return r.json().get('data').get('epoch')

def coinbase_txns():
    headers = {
        'content-type':'application/json',
        'CB-ACCESS-KEY': cb_access_key,
        'CB-ACCESS-SIGN': x,
        'CB-ACCESS-TIMESTAMP': coinbase_time()
    }
    url = 'https://api.coinbase.com/v2/accounts/:account_id/transactions'

def cb_get_currencies():
    url = 'https://api.exchange.coinbase.com/currencies'
    headers = {'Content-Type': 'application/json'}
    r = requests.get(url)
    return r

def cb_get_coins():
    url = 'https://api.coinbase.com/v2/currencies/crypto'
    headers = {'Content-Type': 'application/json'}
    r = requests.get(url)
    return r

    ''' 
    r.json().get('data') = 
    [
  {
    "code": "BTC",
    "name": "Bitcoin",
    "color": "#F7931A",
    "sort_index": 100,
    "exponent": 8,
    "type": "crypto",
    "address_regex": "^([13][a-km-zA-HJ-NP-Z1-9]{25,34})|^(bc1[qzry9x8gf2tvdw0s3jn54khce6mua7l]([qpzry9x8gf2tvdw0s3jn54khce6mua7l]{38}|[qpzry9x8gf2tvdw0s3jn54khce6mua7l]{58}))$",
    "asset_id": "5b71fc48-3dd3-540c-809b-f8c94d0e68b5"
  },
  {
    "code": "ETH",
    "name": "Ethereum",
    "color": "#627EEA",
    "sort_index": 102,
    "exponent": 8,
    "type": "crypto",
    "address_regex": "^(?:0x)?[0-9a-fA-F]{40}$",
    "asset_id": "d85dce9b-5b73-5c3c-8978-522ce1d1c1b4"
  },
    '''