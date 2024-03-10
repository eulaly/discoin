from os import getenv, listdir, remove
import asyncio
import requests
import datetime as dt
from json import dump as jdump
import logging 
from pymongo import MongoClient
from bson import ObjectId
import discord
from discord.ext import commands, tasks
from typing import Literal, Optional
# from coinbase import CoinbaseWalletAuth

discoin_owner_id = int(getenv("discoin_owner_id"))
cg_demo_key = getenv("cg_demo_key")
cb_access_key = getenv("cb_access_key")
mongo_client = MongoClient(getenv('mongodb_url')).discoin  #"mongo_client" is almost certainly...safer
mongodb = MongoClient(getenv('mongodb_url')).discoin
quickchart_url = getenv("quickchart_url")
discoin_version = 'v2.0a'
logger = logging.getLogger(f'discoin {discoin_version}')

#region Non-command functions
def chunker(lst, n):
    """Yield successive `n`-sized chunks from list `lst` of known length."""
    for i in range(0, len(lst), n):
        yield lst[i:i+n]

def search_coins(keyword:str):
    '''broad search of coingecko coin listings'''
    # if the search term matches coingecko id already, return it:
    cgid = mongo_client.coingecko.distinct('id')
    if keyword in cgid: 
        return mongo_client.coingecko.find_one({'id':keyword})
    # otherwise, fuzzy search the term:
    else: 
        return [x for x in mongo_client.coingecko.find({'$text':{'$search':keyword}},{'_id':0})]

def dbck(coin, key='id') -> dict:
    '''single-coin lookup'''
    r = [x for x in mongodb.coingecko.find({key:coin})]
    if not r:
        raise CoinNotFound
    else:
        return r[0]

def get_quickchart_img(post_data: dict):
    '''returns image file directly'''
    print('creating chart')
    r = requests.post(quickchart_url, json=post_data)
    if r.status_code == requests.codes.ok:
        with open('chart.png', 'wb') as f:
            f.write(r.content)
        print('chart creation True')
        return True
    else:
        print('chart creation False')
        return False

def get_coinvals(coins:list, vs=['usd']) -> dict:
    base = 'https://api.coingecko.com/api/v3/simple/price'
    p = {
        'ids':','.join(coins),
        'vs_currencies':','.join(vs),
        'x_cg_demo_api_key': cg_demo_key,
        }
    r = requests.get(base, params=p)
    return r.json() if r.status_code == 200 else None

def get_stats(orders: list) -> dict:
    coins = set(x.get('currency') for x in orders) #set of currencies in the user's orders
    stats = {}
    coinStats = []
    print('getting coins')
    # coinval = get_coinvals(coins)
    cv = [x for x in mongodb.coin_latest.find({'currency':{'$in':list(coins)}})] #latest values of user currencies
    coinval = dict(zip([x.get('currency') for x in cv],[x.get(x.get('currency')) for x in cv])) #remap to dict for easy lookup
    for coin in coins:
        txns = list(filter(lambda x:x.get('currency')==coin, orders)) #filter orders by this coin
        buys = [x for x in txns if x.get('price') >= 0] #mining counts as buys
        sales = [x for x in txns if x.get('price') < 0]

        #old
        # buyAvg = [x.get('price')/x.get('amount') for x in txns if x.get('price') >= 0]
        # saleAvg = [-1*x.get('price')/x.get('amount') for x in txns if x.get('price') < 0]
        #new 22mar22
        buyAvg = sum([x.get('price') for x in buys])/sum([x.get('amount') for x in buys])
        if not sales:
            saleAvg = 0
        else:
            saleAvg = sum([x.get('price') for x in sales])/sum([x.get('amount') for x in sales])

        d = {
            'coin': coin,
            'coinUSD': coinval.get(coin).get('usd'),  #need to rebuild pymongo call into a dict for this to work
            'coinOwned': sum([x.get('amount') for x in txns]), #buys are positive amount, sales are negative
            'usdSpent': sum([x.get('price') for x in buys]),  #doesnt account for mining
            'avgPurchasePrice': buyAvg,
            'usdProfit': -1*sum([x.get('price') for x in sales]),
            'avgProfitPrice': saleAvg,
            # 'coinVal': coinval.get(coin).get(vs),            
            # 'avgPurchasePrice': sum(buyAvg)/len(buyAvg),
            # 'usdProfit': sum([-1*x for x in saleAvg]),  #old; what is this, why did i do this
            # 'avgProfitPrice': 0 if len(saleAvg) < 1 else sum([x*-1 for x in saleAvg])/len(saleAvg)    #old
        }
        d['coinValue'] = d.get('coinOwned')*d.get('coinUSD')
        if d.get('coinValue') > 0:
            # d['gainLoss'] = (d.get('coinValue')/d.get('usdSpent')-1)*100
            d['gainLoss'] = (d.get('coinUSD') - buyAvg)/buyAvg*100
        else:
            d['gainLoss'] = 0
        coinStats.append(d)
    totalSpent = 0
    totalValue = 0
    totalProfit = 0
    for coin in coinStats:
        totalSpent += coin.get('usdSpent')
        totalValue += coin.get('coinValue')
        totalProfit += coin.get('usdProfit')
    stats = {
        'summary':
            {'totalValue': totalValue,
            'totalSpent': totalSpent,
            'totalGain': totalValue-totalSpent,
            'totalProfit': totalProfit,
            # 'roi': totalValue/totalSpent, #old
            # 'roi': (totalValue-totalSpent)/totalSpent, #better
            'roi': (totalValue-(totalSpent-totalProfit))/(totalSpent-totalProfit),
            'invested': totalSpent-totalProfit,
            },
        'coinStats':coinStats}
    print(stats.get('summary').get('roi'))
    return stats

def coin_hist(coin_id: str, days, vs='usd') -> dict:
    '''get a single coin's value at a date in the past'''
    d = (dt.datetime.now()-dt.timedelta(days=int(days))).strftime('%d-%m-%Y')
    url = 'https://api.coingecko.com/api/v3/coins/'+coin_id+'/history'
    p = {
        'date':(dt.datetime.now()-dt.timedelta(days=int(days))).strftime('%d-%m-%Y'),
        'x_cg_demo_api_key': cg_demo_key,
        'localization':'false',
        }
    r = requests.get(url, params=p)
    print(r.request.url)
    if not r.status_code == 200:
        print(r.status_code)
        raise logging.error
    else:
        val = r.json().get('market_data').get('current_price').get(vs)
        return val

def coin_market(coin_id: str, days:int) -> dict:
    '''given a coin_id and # days in the past,
    returns a dict with dates and corresponding % change from the previous day'''
    url = 'https://api.coingecko.com/api/v3/coins/'+coin_id+'/market_chart/'
    p = {
        'vs_currency':'usd',
        'days':str(days),
        'x_cg_demo_api_key': cg_demo_key,
        }
    # if int(days) >= 30:
    #     p['interval'] = 'daily'  #coingecko handles this automatically 2-21-24
    r = requests.get(url, params=p)
    logger.debug(r.request.url)
    expectedDate = (dt.datetime.today() - dt.timedelta(days=int(days))).strftime('%Y-%m-%d')
    if r.status_code == 200:
        prices = r.json().get('prices')
        unixdates, values = zip(*[(d,v) for d,v in prices])
        dates = [dt.datetime.utcfromtimestamp(d/1000).strftime('%Y-%m-%d') for d in unixdates]
        pcts = [(values[n]-values[0])/values[0]*100 for n in range(len(values))]
        current = values[-1]
        oldest = (dt.datetime.today()-dt.datetime.utcfromtimestamp(unixdates[0]/1000)).days
        print(dates[0], expectedDate)
        logger.info(dates[0], expectedDate)
        err = True if dates[0] != expectedDate else False
        return {'dates': dates, 'values': pcts, 'current': current, 'error':err, 'oldest': oldest, 'oldestDate':dates[0]}
    else:
        print(r.status_code, r.json())
        raise logging.error

def tax_dates(txns: list) -> dict:
    '''return tax dates for a set of txns'''
    txns = sorted(txns, key=lambda x: x.get('date'), reverse=True)
    txn_set = set([x.get('date') for x in txns])

def match_coin(key:str, source:str=None) -> str:
    '''
    match coin from gemini/coinbase code against db coinref.
    '''
    unique = mongo_client.coinref.distinct('coin')
    if key not in unique:
        logger.info(f'Key {key} not found in coinref.')
        return None
    if source:
        coingecko_id = mongo_client.coinref.find_one({source: key})
    else:
        coingecko_id = mongo_client.coinref.find_one({'coin':key})
    return coingecko_id.get('coingecko_id') if coingecko_id else None

def file_import(attachment: discord.File, source: str, userid: str):
    '''import data from csv depending on export?'''
    import pandas as pd
    import csv
    if source == 'coinbase':
        ''' generate a report from your account > Transaction History > generate report > alltime/assets/txns > csv'''
        coinbase = pd.read_csv(attachment, skiprows=7)
        coinbase['ddate'] = pd.to_datetime(coinbase.Timestamp)
        coinbase.set_index(coinbase.ddate, inplace=True)
        coinbase = coinbase.loc[(coinbase['Transaction Type'] == 'Buy') | (coinbase['Transaction Type'] == 'Sell')]
        currencies = list(set(coinbase["Spot Price Currency"].tolist()))
        for x in currencies:
            if x != "USD":
                logger.warn(f'Found buy/sale not listed in USD! Please convert: \n\t {coinbase.loc[coinbase["Spot Price Currency"] == x]}')
                return
        txns = []
        for index, row in coinbase.iterrows():
            currency = row.get("Asset") #load here, match later.
            amount = float(row.get("Quantity Transacted"))
            if row.get("Transaction Type") == 'Sell':
                amount = amount * -1
            price = row.get("Total (inclusive of fees and/or spread)")
            date_str = row.get('ddate').strftime('%Y-%m-%d')
            row_dict = {'date': date_str, 'amount': amount, 'currency': currency, 'price': price, 'userid':userid}
            txns.append(row_dict)
        
        cb_currency = list(set([x.get('currency') for x in txns]))
        logger.info(f'Found {len(cb_currency)} currencies to lookup.')
        
        for t in txns: #lookup/match currency values
            t['currency'] = match_coin(t.get('currency'))

                
    elif source == 'gemini':
        '''gemini transaction_history as of March 2024'''
        gemini = pd.read_excel(attachment)
        gemini['ddate'] = pd.to_datetime(gemini.Date)
        gemini.set_index(gemini.ddate, inplace=True)
        # gd = gemini.filter(like="Amount") \
        #     .apply(lambda row: {'ddate': row.name, **{col: val for col, val in row.items() if pd.notna(val)}}, axis=1) \
        #     .tolist()
        # df.apply(lambda row: {col: val for col, val in row.items() if pd.notna(val)}, axis=1).tolist()
        txns = []
        for index, row in gemini.iterrows():
        # Find the currency column and amount
            currency_col = [col for col in gemini.columns if "Amount" in col and col != "USD Amount USD" and pd.notnull(row[col])]
            if currency_col:
                currency_col = currency_col[0]
                currency = currency_col.split(" ")[0]  # Assuming currency is the first word in the column name
                amount = row[currency_col]
                price = row["USD Amount USD"] * -1
                date_str = index.strftime('%Y-%m-%d')
                row_dict = {'date': date_str, 'amount': amount, 'currency': currency, 'price': price, 'userid':userid}
                txns.append(row_dict)
    
    logger.info(f'Found {len(txns)} txns from {attachment.filename}')
    logger.debug(f'Found {len(txns)} txns from {attachment.filename}:{txns}')

    for t in txns: #lookup/match currency values
        t['currency'] = match_coin(t.get('currency'))

    # save to db
    return txns
    
    #deprecated?
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
    return True
#endregion

class Scheduler(commands.Cog):
    '''
    Scheduler's main job is to call data responsibly, 
    within CoinGecko's public API rate limit of _30 calls/min_ (Feb 2024)
    https://www.coingecko.com/api/documentation
    '''
    def __init__(self, bot):
        self.index = 0
        self.bot = bot
        self.num_users = 0
        self.cleanup.start()
        self.refresh_coinlist.start()
        self.update_coinvals.start()
        logging.debug('Scheduler loaded')

    def cog_unload(self):
        self.update_coinvals.stop()
        self.refresh_coinlist.stop()

    # @tasks.loop(hours=24)
    # async def check_users(self):
    #     self.num_users = len(set([x.get('userid') for x in mongodb.txns.find()]))
    
    @tasks.loop(hours=24)
    async def cleanup(self):
        '''remove files, eg quickchart images'''
        removeableFiles = [f for f in listdir() if f.endswith(('png','json'))]
        for f in removeableFiles:
            remove(f)
        logger.info(f'Cleanup removed {len(removeableFiles)} files.')
        return

    @tasks.loop(hours=24)
    async def refresh_coinlist(self):
        '''check coingecko for new coins'''
        r = requests.get(f'https://api.coingecko.com/api/v3/coins/list',params={'x_cg_demo_api_key':cg_demo_key})
        if r.status_code == 200:
            mongo_client.coingecko.delete_many({})
            mongo_client.coingecko.insert_many(r.json())
            logger.info(f'Found {len(r.json())} coins, added to mongodb discoin.coingecko')

    @tasks.loop(minutes=5)
    async def update_coinvals(self, vs=['usd']):
        '''
        replaces coin_latest collection with up-to-date data from /simple/price.
        updated every 5 min.
        '''
        coins = list(set([x.get('currency') for x in mongo_client.txns.find()]))
        base = 'https://api.coingecko.com/api/v3/simple/price'
        p = {
            'ids':','.join(coins),
            'vs_currencies':','.join(vs),
            'x_cg_demo_api_key':cg_demo_key,
            'include_last_updated_at':'true',  #appends UTC timestamp to each coin value
            }
        r = requests.get(base, params=p)
        if r.status_code == 200:
            coinvals = [{k:v, 'currency':k} for k,v in r.json().items()] # `currency` field reqd for filtering
            mongo_client.coin_latest.delete_many({})
            mongo_client.coin_latest.insert_many(coinvals)
            logger.info(f'Updated {len(coinvals)} coin values')
            logger.debug(f'Updated coins: {coins}')

class CoinNotFound(commands.CommandError):
    def __init__(self, *args, **kwargs):
        self.msg = '''CoinNotFound error message: try again nerd'''
        super().__init__(*args, **kwargs)

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix = '/', intents=intents)

#region Bot Commands

@bot.event
async def on_ready():
    guilds_info = '\n'.join([f"\t {i}. {x.id} - {x.name}" for i,x in enumerate(bot.guilds,start=1)])
    logger.info(f'{bot.user} has connected to {len(bot.guilds)} servers:\n{guilds_info}')

@bot.tree.command(name='test', description='test')
async def _test(ixn: discord.Interaction, type:str, num:int, coin:str):
    logging.info(f'{dt.datetime.now()} test')
    print(f'num={num}')
    if type == "channel":
        await ixn.channel.send('channel test')
    if type == "reaction":
        await ixn.message.add_reaction('✅')
    else: 
        await ixn.response.send_message('test')

@bot.tree.command(name="cryptohelp", description="Discoin commands and instructions")
async def _cryptohelp(ixn: discord.Interaction):
    prefix = bot.command_prefix
    msg = discord.Embed(
        title=":information_source:  Discoin Help",
        type="rich",
        color=discord.Color.orange(),
        description=f'''Discoin can help you track crypto performance. 
        I usually respond in a private message. 
        *Discoin does not buy or sell any crypto*
        Commands (italics args optional):
        • **`{prefix}buy [amount of crypto] [cryptocurrency] [$USD paid]`** *`[YYYY-MM-DD]`* add a purchase to your portfolio. if no date is provided, today's date will be used.
        • **`{prefix}sell [amount of crypto] [cryptocurrency] [$USD paid]`** *`[YYYY-MM-DD]`* add a sale to your portfolio. if no date is provided, today's date will be used.
        • **`{prefix}coin`** dm your portfolio performance 
        • **`{prefix}search [coin]`** search supported coins eg (`eth`, `btc`)
        • **`{prefix}market [coin] [# days]`** coin performance from N days ago
        • **`{prefix}compare [coin1] [coin2] [# days]`** display two coins' performance from N days ago
        • **`{prefix}txns`** *`[cryptocurrency]`* show all your txns; or show those with a specific coin
        • **`{prefix}delete [transaction id]`** remove one of your txns by id; use `!txns` first
        • **`{prefix}export`** dm you your data in JSON format
        • **`{prefix}wipe`** remove all your data from this bot
        • **`{prefix}discoindev [message]`** message the dev

        [Want me in your server? Click here](https://discord.com/api/oauth2/authorize?client_id=907807464441909289&permissions=139586882624&scope=bot%20applications.commands)
        Support me: [Ko-fi](https://ko-fi.com/eulaly)
        LTC ||`ltc1qqcmyulnyx97a2sx4q9n3gmxqctgyg09y37ljsg`||
        ''')
    print(f'cryptohelp message length: {len(msg)}')
    #if len(msg) > 5999:
    #    raise _cryptohelp.error?
    msg.set_footer(
        text="""Discoin v2.0a - Market data powered by CoinGecko
        Data is delayed 5m+ (I'm poor)
        NFTs, options chains not supported.
        """,
        #icon_url="",
    )
    await ixn.response.send_message(embed=msg)
    # await ctx.author.send(embed=msg)

# UNTESTED - typed
@bot.tree.command(name="buy", description="Add purchase (USD). default to today's date")
async def _buy(ixn: discord.Interaction, amount: float, currency: str, price:float, date:str=None):
    '''add a purchase to your portfolio. 
    if no date is provided, today's date will be used.
    currently only supports USD purchases
    '''
    #not needed? 
    # r = requests.get('https://api.coingecko.com/api/v3/coins/'+currency,params={'x_cg_demo_api_key':cg_demo_key})
    # if not r.status_code == 200:
    # replaced with below line:
    if currency not in [x for x in mongo_client.coingecko.distinct('id')]:

        coinList = search_coins(currency)
        msg = '''Coin not found. Did you mean one of these?
    • `!buy` and `!sell` use coin **`id`** (no caps, use dashes instead of spaces)
    • comparison arguments need **`symbol`**
    Try **`!search [coin name]`** or check coingecko.com for the full list
    Symbol \t | \t Name \t | \t id \n'''
        for coin in coinList[:5]:
            msg+=f'```{coin.get("symbol")}\t{coin.get("name")}\t{coin.get("id")}```'
        msg+= 'Try **`!search [coin name]`** or check coingecko.com for the full list'
        await ixn.response.send_message(msg)
    else:
        if not date:
            date = dt.datetime.today().strftime('%Y-%m-%d')
        txn = {
            'amount': amount,
            'currency': currency,
            'price': price,
            'date': date,
            'userid':str(ixn.user.id)
            }
        mongodb.txns.insert_one(txn)
        await ixn.user.send(f'{ixn.user.name} bought {amount} {currency} for {price} USD')

# UNTESTED
@bot.tree.command(name="sell", description="Add sale (USD). default to today's date")
async def _sell(ixn:discord.Interaction, amount:float, currency:str, price:float, date:str=None):
    '''add a sale to your portfolio. if no date is provided, today's date will be used.'''
    await _buy(ixn=ixn, amount=-1*float(amount), currency=currency, price=-1*float(price), date=date)

# UNTESTED 
@bot.tree.command(name="coin", description="pm you your portfolio. updated every 5 min")
async def _coin(ixn:discord.Interaction, flex:discord.Member=None):  # add support for other currencies ('vs')
    '''pm you your portfolio'''
    userTxns = [x for x in mongodb.txns.find({'userid':str(ixn.user.id)})]
    if not userTxns:
        msg = "No orders found. Add crypto purchases to your portfolio with: ```/txn {amount of crypto} {cryptocurrency} {$USD paid}```"
        embed = None
        await ixn.send(msg)
        return
    else:
        # ixn.response.defer(thinking=True)
        stats = get_stats(userTxns)
        sstats = sorted(stats.get('coinStats'), key=lambda x:x.get('coinValue'), reverse=True)
        pv = "{:,.2f}".format(stats.get('summary').get('totalValue'))
        # roi = round(stats.get('summary').get('totalValue')/stats.get('summary').get('totalSpent')*100-100,2)
        roi = round(stats.get('summary').get('roi')*100,2)
        # invested = "{:,.2f}".format(stats.get("summary").get("totalSpent")) 
        invested = "{:,.2f}".format(stats.get("summary").get("invested"))
        profit = "{:,.2f}".format(stats.get("summary").get("totalProfit"))
        desc = 'amt coin ROI% (value)'
        for coin in sstats:
            desc += f'''\n**{round(coin.get("coinOwned"), 2)} {coin.get("coin")} {round(coin.get("gainLoss"), 2)}% \
            (${"{:.2f}".format(coin.get("coinValue"))})**
                    | spent (${"{:.2f}".format(coin.get("usdSpent"))}) @ avg ${"{:.2f}".format(coin.get("avgPurchasePrice"))}'''
            if coin.get("usdProfit") > 0:
                desc+=f'''\n | sold ${"{:.2f}".format(coin.get("usdProfit"))} @ avg ${"{:.2f}".format(coin.get("avgProfitPrice"))}'''

        roiList = [c.get('gainLoss') for c in sstats]
        coinNames  = [c.get('coin') for c in sstats]
        roiChart = {'chart': {'type': 'bar', 'data': {'labels': coinNames,
            'datasets': [{'label': 'ROI per coin (%)', 'data':roiList, 'backgroundColor':'#db9d16'}]}},'backgroundColor': '#2f3136'}
        chartfile = discord.File("chart.png") if get_quickchart_img(roiChart) else None
        
        embed = discord.Embed(title=f':coin:  {ixn.user.name}\'s Portfolio: ${pv} \n {roi}% ROI for ${invested} invested \n ${profit} realized',
            description=desc, color=discord.Color.dark_gold(), type='rich')
        embed.set_image(url=f'attachment://chart.png')

        if flex:
            await ixn.followup.send(flex, embed=embed, file=chartfile)
            return
        msg = '' #consider adding timestamp?
        # print(f' follow up: {ixn.followup.channel.name}')
        # await ixn.followup.send(msg, embed=embed, file=chartfile)
        await ixn.response.send_message(msg, embed=embed,file=chartfile)

#UNTESTED
@bot.tree.command(name="flex", description = 'flex on the boys. tag a boy to flex on him')
async def _flex(ixn:discord.Interaction, target: discord.Member=None):
    '''flex on the boys. tag a boy to flex on him'''
    if blocked(user=(ixn.user.name+'#'+ixn.user.discriminator), type='flex'):
        return
    if target:
        msg = f'{ixn.user.mention} 💪FLEXED💪 ON {target.mention}'
    else:
        msg = f'{ixn.channel.mention} {ixn.user.mention} 💪FLEXED💪 ON ALL YOU FOOLS! TIME TO SELL'
    await _coin(ixn=ixn, flex=msg)
@_flex.error
async def flex_error(ixn:discord.Interaction, error):
    msg = f'''{ixn.user.mention} 💪FLEXED💪 ON {ixn.user.mention}\'s OWN SELF!! 
    😤 BOO THIS MAN!! HE PROBABLY HEDGES WITH 💰FIAT💰'''
    await _coin(ixn=ixn, flex=msg)

# UNTESTED
@bot.tree.command(name="search", description="search for supported coins; favors coin symbol")
async def _search(ixn:discord.Interaction, keyword:str):
    '''search for supported coins. favors coin symbol'''
    coinList = search_coins(keyword=keyword)
    msg = f'''Here are the first 10 results for `{keyword}`: \nSymbol \t | \t Name \t | \t id'''
    for coin in coinList[:10]:
        msg+=f'''```{coin.get("symbol")}\t{coin.get("name")}\t{coin.get("id")}```'''
    msg+= '''• You must use this exact `id` for `/buy`, `/sell`, `/market`, and `/compare`'''
    if not coinList:
        msg = '''No results. Try again, or check [CoinGecko](https://www.coingecko.com/en/all-cryptocurrencies).'''
    await ixn.channel.send(msg)

#UNTESTED
@bot.tree.command(name="market", description="get market data for a coin")
async def _market(ixn:discord.Interaction, coin_id:str, days:int=90, vs:str='usd'):
# async def _market(ixn:discord.Interaction, coin_id: str, days:int=90, vs:str='usd'):
    '''get market data for a coin'''
    coin = dbck(coin_id).get('id')
    data = coin_market(coin, days=days)
    #error handling for `/market_chart` which returns 200 json() without 'market_data' if date is too old
    if data.get('error') == True:  # this appears not to work. coingecko might auto-adjust this now. [2024-03-02]
        await ixn.channel.send(f'Rerunning with oldest available date ({days} days ago)')
        days = data.get('oldest')
        data = coin_market(coin,days=days)
    coinval_date = coin_hist(coin, days=days)
    logging.info(f'market - {type(coinval_date)} {coinval_date}')
    logging.info(f'market - {type(data)} {data.get("values")}')
    chart = {'chart':{'type':'line', 'data':{
        'labels':data.get('dates'),
        'datasets':[{'label':coin,'data':data.get('values'),'borderWidth':1, 'pointRadius':1, 'fill': 'False'}],
        }},
        'backgroundColor':'#2f3136',
        }
    chartfile = discord.File("chart.png") if get_quickchart_img(chart) else None
    emb = discord.Embed(title=f'{coin} % change since {data.get("dates")[0]}',
        description=f'{coin}: {round(data.get("values")[-1],4)}% from {round(coinval_date,2)} {vs} to {round(data.get("current"),2)}', type='rich')
    emb.set_image(url=f'attachment://chart.png')
    await ixn.channel.send(embed=emb,file=chartfile)
@_market.error
async def _market_error(ixn:discord.Interaction, error: CoinNotFound):
    logger.info(error)
    if isinstance(error, CoinNotFound):
        await ixn.channel.send(error.msg)

#UNTESTED
@bot.tree.command(name="compare", description='compare performance of 2 coins')
async def _compare(ixn:discord.Interaction, id1:str, id2:str, days:int=90):
    # try up to x coins, if ValueError that should be the date, else days=90
    '''compare performance of 2 coins'''
    c1 = dbck(id1)
    c2 = dbck(id2)
    c1market = coin_market(c1.get('id'), days=days)
    c2market = coin_market(c2.get('id'), days=days)
    #error handling for `/market_chart` which returns 200 json() without 'market_data' if date is too old
    if c1market.get("oldestDate") != c2market.get("oldestDate"): 
        days = min([c1market.get("oldest"),c2market.get("oldest")])
        await ixn.channel.send(f'Rerunning with oldest available date ({days} days ago)')
        c1market = coin_market(c1.get('id'), days=days)
        c2market = coin_market(c2.get('id'), days=days)
    c1date = coin_hist(c1.get('id'), days=days)
    c2date = coin_hist(c2.get('id'), days=days)
    chart = {'chart':{'type':'line', 'data':{
        'labels':c1market.get('dates'),
        'datasets':[
            {'label':id1,'data':c1market.get('values'),'borderWidth':1, 'pointRadius': 1, 'fill': 'False'},
            {'label':id2,'data':c2market.get('values'),'borderWidth':1, 'pointRadius': 1, 'fill': 'False'}
            ],
        }},
        'backgroundColor':'#2f3136',
        }
    chartfile = discord.File("chart.png") if get_quickchart_img(chart) else None
    emb = discord.Embed(title=f'{id1} vs {id2} relative % change since {c1market.get("dates")[0]}',
        description=f'{id1}: {round(c1market.get("values")[-1],4)}% from ${"{:,.2f}".format(c1date)} to ${round(c1market.get("current"),2)}\n \
            {id2}: {round(c2market.get("values")[-1],4)}% from ${"{:,.2f}".format(c2date)} to ${round(c2market.get("current"),2)}', type='rich') 
    emb.set_image(url=f'attachment://chart.png')
    await ixn.channel.send(embed=emb,file=chartfile)

@_compare.error
async def _compare_error(ixn:discord.Interaction, error):
    if isinstance(error, CoinNotFound):
        logger.error(error.msg)
        print(error.msg)
        await ixn.channel.send(error.msg)

@bot.command(name="txns")
async def _txns(ctx, coin=None):
    '''find all your txns with a specific coin'''
    searchTerms = {'userid':str(ctx.author.id)}
    if coin:
        searchTerms['currency'] = coin
    data = [x for x in mongodb.txns.find(searchTerms)]
    msg = "Your transactions"
    if coin: 
        msg += f" with {coin}"
    msg+= f'\n To delete a transaction, find the txn id and type `!delete [txnid]`'
    chunked = list(chunker(data,20))
    for l in chunked:                       #discord's 2k char limit is hit @ ~25 txns
        for d in l:
            msg+= f'\n`{str(d.get("_id"))}` *${d.get("price")} exchanged for {d.get("amount")} {d.get("currency")} on {d.get("date")}*'
            # if dt.datetime.today() - dt.strptime(d.get('date'), '%Y-%m-%d') > 365:
                # msg+= f'\n```css\n{str(d.get("_id"))}` *${d.get("price")} exchanged for {d.get("amount")} {d.get("currency")} on {d.get("date")}*'
        # add reaction to see next page? 
        # sort by most recent txns
        await ctx.author.send(msg)
        msg = ""

@bot.command(name="delete")
async def _delete(ctx, txnid):
    '''remove a txn from your orders by id'''
    mongodb.txns.delete_one({'_id':ObjectId(txnid), 'userid':str(ctx.author.id)})
    await ctx.message.add_reaction('✅')

@bot.tree.command(name="import", description="import txns from coinbase or gemini")
async def _import(ixn: discord.Interaction, file:discord.Attachment, source: Literal['coinbase', 'gemini']):
    '''import txns from coinbase or gemini.'''
    txns = file_import(attachment=file, source=source, userid=str(ixn.user.id))
    msg = discord.Embed(
        title=f"{source} Transactions",
        type = "rich",
        color = discord.Color.orange(),
        description=f'''Found {len(txns)} transactions: ''')
    msg.add_field(name='', value='`date\tamount\tcurrency\tprice`')
    for i, x in enumerate(txns[:21]):
        msg.add_field(name=i+1, value=f"`{x.get('date')}\t{x.get('amount')}\t{x.get('currency')}\t${x.get('price')}`")
    # TODO check , is this correct?
    # TODO add userid
    # TODO for each txn, _buy()
    await ixn.user.send('')

@bot.tree.command(name="export", description="dm your data in JSON format")
async def _export(ixn: discord.Interaction):
    '''dm your data in JSON format'''
    auth = str(ixn.user.id)
    data = [x for x in mongodb.txns.find({'userid':auth})]
    for d in data:
        d['_id'] = str(d.get('_id'))
    export = {'txns':data}
    with open(f'{auth}.json', 'w', encoding='utf-8') as f:
        jdump(export, f, indent=4, ensure_ascii=False, separators=(',', ':'), sort_keys=True)
    await ixn.user.send(file=discord.File(f'{auth}.json'))

@bot.command(name="wipe")
async def _wipe(ctx):
    '''remove all your data from this bot'''
    mongodb.txns.delete_many({'userid':str(ctx.author.id)})
    ck = [x for x in mongodb.txns.find({'userid': str(ctx.author.id)})]
    if len(ck) == 0:
        await ctx.message.add_reaction('✅')
        await ctx.author.send('nice knowing you')
    else:
        await ctx.author.send('Something went wrong.')

#endregion

#region Dev Commands

@bot.command(name="discoindev")
async def _contactdev(ctx):
    '''send a message to the devs'''
    if blocked(user=(ctx.author.name+'#'+ctx.author.discriminator), type='dev'):
        return
    embed = discord.Embed(title=f'🔧 Dev Message from {ctx.author.name}#{ctx.author.discriminator}', type='rich',
        description=f'{ctx.author.display_name} ({ctx.author.id}) from {ctx.message.guild} says: {ctx.message.content}',
        color=discord.Color.blue())
    devch = bot.get_channel(456908681330688000)
    await devch.send(None, embed=embed)
@_contactdev.error
async def dev_error(ctx, error):
    if isinstance(error, commands.errors.CommandOnCooldown):
        await ctx.channel.send(f'{ctx.author.display_name} please try again later')

@bot.command(name="ddev")
@commands.is_owner()
async def _ddev(ixn: discord.Interaction):
    msg = f'''
        • **`!devblock [userid] [type]`** userid is a name, type = flex or /
        '''
    await ixn.user.send(msg)

def blocked(user: str, type: str) -> bool:
    blocked = [x for x in mongodb.blocked.find({'userid':user, 'type':type})]
    return True if blocked else False

@bot.tree.command(name="devblock")
@commands.is_owner()
async def _devblock(ixn:discord.Interaction, userid:int, kw:str):  # fix args?
    mongodb.blocked.insert_one({'user':userid, 'type':kw})
    logger.info(f'dev blocked {userid} for {kw}')
    await ixn.user.send(f'blocked userid {userid} for {kw}')

@bot.tree.command(name="devunblock")
@commands.is_owner()
async def _devblock(ixn:discord.Interaction, userid:int, kw:str):   #fix args? 
    mongodb.blocked.delete_one({'user':userid, 'type':kw})
    logger.info(f'dev unblocked {userid} for {kw}')
    await ixn.user.send(f'unblocked userid: {userid} for {kw}')

#endregion

@bot.command(name="sync", description="sync bot commands")
@commands.is_owner()
async def _sync(ctx: commands.Context, guilds: commands.Greedy[discord.Object], spec: Optional[Literal["~", "*", "^"]] = None) -> None:
    if not guilds:
        if spec == "~":
            synced = await ctx.bot.tree.sync(guild=ctx.guild)
        elif spec == "*":
            ctx.bot.tree.copy_global_to(guild=ctx.guild)
            synced = await ctx.bot.tree.sync(guild=ctx.guild)
        elif spec == "^":
            ctx.bot.tree.clear_commands(guild=ctx.guild)
            await ctx.bot.tree.sync(guild=ctx.guild)
            synced = []
        else:
            synced = await ctx.bot.tree.sync()

        await ctx.send(
            f"Synced {len(synced)} commands {'globally' if spec is None else 'to the current guild.'}"
        )
        logger.info(f"Synced {len(synced)} commands {'globally' if spec is None else 'to the current guild.'}")
        return

    ret = 0
    for guild in guilds:
        try:
            await ctx.bot.tree.sync(guild=guild)
        except discord.HTTPException:
            pass
        else:
            ret += 1
    logger.info(f"Synced the tree to {ret}/{len(guilds)}.")
    await ctx.author.send(f"Synced the tree to {ret}/{len(guilds)}.")


async def main():
    discord.utils.setup_logging(level=logging.INFO, root=True)
    async with bot:
        await bot.add_cog(Scheduler(bot=bot))
        bot.tree.copy_global_to(guild=discord.Object(id='127214262123888640'))  # we copy the global commands we have to a guild, this is optional
        await bot.start(getenv('discoin_token'))
    
asyncio.run(main())