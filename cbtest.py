import pandas as pd

txns = import_cb('assets/potato_coinbase.csv','potato')

def import_cb(attachment:str, userid: str):
    '''import data from coinbase.
    generate a report from your account > Transaction History
     > generate report > alltime/assets/txns > csv
    '''
    # check file is csv
    coinbase = pd.read_csv(attachment, skiprows=7)
    coinbase['ddate'] = pd.to_datetime(coinbase.Timestamp)
    # think about this . . .
    currencies = list(set(coinbase["Spot Price Currency"].tolist()))
    for x in currencies:
        if x != "USD":
            print(f'Found buy/sale not listed in USD! Please convert: \n\t {coinbase.loc[coinbase["Spot Price Currency"] == x]}')
            return
    buy_type = ['Advanced Trade Buy','Buy','Learning Reward','Receive', 'Rewards Income']
    sale_type = ['Sell','Send']
    txns = []
    coinbase['Total (inclusive of fees and/or spread)'] = coinbase['Total (inclusive of fees and/or spread)'].fillna(0)
    # coinbase.fillna({'Total (inclusive of fees and/or spread)':0}, inplace=True)
    for _, row in coinbase.iterrows():
        currency = row.get("Asset") #load here, match later.
        amount = float(row.get("Quantity Transacted"))
        price = row.get("Total (inclusive of fees and/or spread)")
        if row.get("Transaction Type") in sale_type:
            amount = amount * -1
            price = price * -1
            if row.get("Transaction Type") == 'Rewards Income':
                price = 0
        date_str = row.get('ddate').strftime('%Y-%m-%d')
        row_dict = {'date': date_str, 'amount': amount, 'currency': currency, 'price': price, 'userid':userid}
        if row["Transaction Type"] == "Convert":    #create inverse txn for gained coin
            row_pair = row_dict
            row_pair['currency'] = row["Notes"].split(' ')[-1]  # "Converted [Quantity1] [Asset1] to [Quantity2] [Asset2]"    
            row_pair['amount'] = row["Notes"].split(' ')[-2]  
            txns.append(row_pair)
        txns.append(row_dict)
    cb_currency = list(set([x.get('currency') for x in txns]))
    print(f'Found {len(cb_currency)} currencies to lookup.')
    coinbase['coingecko'] = coinbase['Asset'].apply(cb_cg)
    unmatched = coinbase[coinbase['coingecko'].isna()]
    if not unmatched.empty:
        unmatched_coins = list(set(unmatched.Asset.tolist()))
        print(f'Found {len(unmatched_coins)} unmatched coins:\n {unmatched_coins}')
    else: 
        print(f'Matched {len(set(coinbase.Asset.tolist()))} coins successfully.')
        # mongo_client.txns.insert_many(txns)
    print(f'Found {len(txns)} txns from {attachment}')
    return txns   

def old_cb_import(attachment):
    with open(attachment) as csvfile:
        data = [x for x in csv.reader(csvfile)]
    cb_txns = [dict(zip(data[0],y)) for y in data[1:]]
        # this won't work for deposits!  
        # coinbase deposits (and withdrawals?) don't have an order id, they have a 'trade id'
    uids = set([x.get('order id') for x in cb_txns]) #combine USD match, coin match, and fee txns into single dict
    txns = []
    for uid in filter(bool,uids):
        d = {'cborderid':uid}
        for c in filter(lambda x: x.get('order id')==uid, cb_txns):
            if c.get('type') != 'fee' and c.get('amount/balance unit') == 'USD':
                d['price'] = abs(float(c.get('amount')))
            d['date'] = dt.datetime.strptime(c.get('time'),'%Y-%m-%dT%H:%M:%S.%fZ').strftime('%Y-%m-%d')
            if c.get('amount/balance unit') != 'USD':
                d['amount'] = c.get('amount')
                d['currency'] = c.get('amount/balance unit')
            else:
                d['price'] = c.get('amount')
        txns.append(d)