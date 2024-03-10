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