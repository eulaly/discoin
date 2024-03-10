import pandas as pd

def file_import(attachment:str,source:str):
    print(source)
    txns = []
    if source == 'coinbase':
        ''' generate a report from your account > Transaction History > generate report > alltime/assets/txns > csv'''
        coinbase = pd.read_csv(attachment, skiprows=7)
        print('loaded coinbase')
        coinbase['ddate'] = pd.to_datetime(coinbase.Timestamp)
        coinbase = coinbase.loc[(coinbase['Transaction Type'] == 'Buy') | (coinbase['Transaction Type'] == 'Sell')]
        currencies = list(set(coinbase["Spot Price Currency"].tolist()))
        print(currencies)
        for x in currencies:
            if x != "USD":
                print(f'Found buy/sale not listed in USD! Please convert: \n\t {coinbase.loc[coinbase["Spot Price Currency"] == x]}')
                return
        print('iter')
        for index, row in coinbase.iterrows():
            currency = row.get("Asset")
            amount = float(row.get("Quantity Transacted"))
            if row.get("Transaction Type") == 'Sell':
                amount = amount * -1
            price = row.get("Total (inclusive of fees and/or spread)")
            date_str = row.get('ddate').strftime('%Y-%m-%d')
            row_dict = {'date': date_str, 'amount': amount, 'currency': currency, 'price': price}
            txns.append(row_dict)
        print(f'fonud {len(txns)} txns')
    elif source == 'gemini':
        '''gemini transaction_history as of March 2024'''
        gemini = pd.read_excel(attachment)
        print('loaded gemini')
        gemini['ddate'] = pd.to_datetime(gemini.Date)
        gemini.set_index(gemini.ddate, inplace=True)
        # gd = gemini.filter(like="Amount") \
        #     .apply(lambda row: {'ddate': row.name, **{col: val for col, val in row.items() if pd.notna(val)}}, axis=1) \
        #     .tolist()
        # df.apply(lambda row: {col: val for col, val in row.items() if pd.notna(val)}, axis=1).tolist()
        for index, row in gemini.iterrows():
        # Find the currency column and amount
            currency_col = [col for col in gemini.columns if "Amount" in col and col != "USD Amount USD" and pd.notnull(row[col])]
            if currency_col:
                currency_col = currency_col[0]
                currency = currency_col.split(" ")[0]  # Assuming currency is the first word in the column name
                amount = row[currency_col]
                price = row["USD Amount USD"] * -1
                date_str = index.strftime('%Y-%m-%d')
            
                # Construct dictionary and append to list
                row_dict = {'date': date_str, 'amount': amount, 'currency': currency, 'price': price}
                txns.append(row_dict)
        print(f'fonud {len(txns)} txns')
    print(f'done')
    return txns