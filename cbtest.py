import pandas as pd

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
    for _, row in coinbase.iterrows():
        if row.get("Transaction Type") == "Convert": # FIX - from [Asset] to [regex last word (space) from 'Notes']
            continue                # add 2nd txn? loss 1 coin, gain another? 
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
    print(f'Found {len(txns)} txns from {attachment}')
    # mongo_client.txns.insert_many(txns)
    return txns   