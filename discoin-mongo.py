from logging import error, INFO
from os import getenv, listdir, remove
import requests
import datetime as dt
import json
from pymongo import MongoClient
from bson import ObjectId

from discord import Embed, Color, File, Member
from discord.ext import commands, tasks
from discord.ext.commands.errors import CommandError

# Non-command functions
mongourl = getenv('mongodb_url')
client = MongoClient(mongourl)

def chunker(lst, n):
    """Yield successive `n`-sized chunks from list `lst` of known length."""
    for i in range(0, len(lst), n):
        yield lst[i:i+n]

def search_coins(keyword):
    db = client.coinref
    return [x for x in db.coinref.find({'$text':{'$search':keyword}},{'_id':0})]

def dbck(coin, key='id') -> dict:
    db = client.coinref
    r = [x for x in db.coinref.find({key:coin})]
    if not r:
        raise CoinNotFound
    else:
        return r[0]

def get_quickchart_img(post_data: dict):
    '''returns image file directly'''
    print('creating chart')
    url = 'http://192.168.1.207:8888/chart'
    r = requests.post(url, json=post_data)
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
    p = {'ids':','.join(coins),'vs_currencies':','.join(vs)}
    r = requests.get(base, params=p)
    return r.json() if r.status_code == 200 else None

def get_stats(orders: list) -> dict:
    coins = set(x.get('currency') for x in orders) #set of currencies in the user's orders
    stats = {}
    coinStats = []
    print('getting coins')
    # coinval = get_coinvals(coins)
    db = client.coin_latest
    cv = [x for x in db.coin_latest.find({'currency':{'$in':list(coins)}})] #latest values of user currencies
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

def coin_hist(coin_id: str, days) -> dict:
    d = (dt.datetime.now()-dt.timedelta(days=int(days))).strftime('%d-%m-%Y')
    url = 'https://api.coingecko.com/api/v3/coins/'+coin_id+'/history'
    p = {'date':d}
    r = requests.get(url, params=p)
    print(r.request.url)
    if not r.status_code == 200:
        print(r.status_code)
        raise error        
    else:
        val = r.json().get('market_data').get('current_price').get('usd')
        return val

def coin_market(coin_id: str, days) -> dict:
    '''given a coin_id and # days in the past,
    returns a dict with dates and corresponding % change from the previous day'''
    url = 'https://api.coingecko.com/api/v3/coins/'+coin_id+'/market_chart/'
    p = {'vs_currency':'usd','days':str(days)}
    expectedDate = (dt.datetime.today() - dt.timedelta(days=int(days))).strftime('%Y-%m-%d')
    if int(days) >= 30:
        p['interval'] = 'daily'
    r = requests.get(url, params=p)
    print(r.request.url)
    if r.status_code == 200:
        prices = r.json().get('prices')
        unixdates, values = zip(*[(d,v) for d,v in prices])
        dates = [dt.datetime.utcfromtimestamp(d/1000).strftime('%Y-%m-%d') for d in unixdates]
        pcts = [(values[n]-values[0])/values[0]*100 for n in range(len(values))]
        current = values[-1]
        oldest = (dt.datetime.today()-dt.datetime.utcfromtimestamp(unixdates[0]/1000)).days
        print(dates[0], expectedDate)
        err = True if dates[0] != expectedDate else False
        return {'dates': dates, 'values': pcts, 'current': current, 'error':err, 'oldest': oldest, 'oldestDate':dates[0]}
    else:
        print(r.status_code, r.json())
        raise error

def tax_dates(txns: list) -> dict:
    '''return tax dates for a set of txns'''
    txns = sorted(txns, key=lambda x: x.get('date'), reverse=True)
    txn_set = set([x.get('date') for x in txns])

def file_import(attachment, source):
    '''import data from csv depending on export?'''
    if source == 'coinbase':
        import csv
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
            if c.get('type') is not 'fee' and c.get('amount/balance unit') == 'USD':
                d['price'] = abs(float(c.get('amount')))
            d['date'] = dt.datetime.strptime(c.get('time'),'%Y-%m-%dT%H:%M:%S.%fZ').strftime('%Y-%m-%d')
            if c.get('amount/balance unit') != 'USD':
                d['amount'] = c.get('amount')
                d['currency'] = c.get('amount/balance unit')
            else:
                d['price'] = c.get('amount')
        txns.append(d)
    return True

class Scheduler(commands.Cog):
    def __init__(self, bot):
        self.index = 0
        self.bot = bot
        print('Scheduler loaded.')
        self.cleanup.start()
        self.refresh_coinlist.start()
        self.update_coinvals.start()

    def cog_unload(self):
        self.update_coinvals.stop()
        self.refresh_coinlist.stop()

    @tasks.loop(hours=24)
    async def cleanup(self):
        removeableFiles = [f for f in listdir() if f.endswith(('png','json'))]
        for f in removeableFiles:
            remove(f)
        print(f'{len(removeableFiles)} removed.')
        return

    @tasks.loop(hours=24)
    async def refresh_coinlist(self):
        db = client.coinref
        r = requests.get('https://api.coingecko.com/api/v3/coins/list')
        if r.status_code == 200:
            db.coinref.delete_many({})
            db.coinref.insert_many(r.json())
            print('coin reference updated')

    @tasks.loop(minutes=5)
    async def update_coinvals(self, vs=['usd']):
        '''replaces coin_latest collection with up-to-date data from /simple/price'''
        db = client.txns
        coins = list(set([x.get('currency') for x in db.txns.find()]))
        print(f'updating values for {coins}')
        base = 'https://api.coingecko.com/api/v3/simple/price'
        p = {'ids':','.join(coins),'vs_currencies':','.join(vs)}
        r = requests.get(base, params=p)
        if r.status_code == 200:
            coinvals = [{k:v, 'currency':k} for k,v in r.json().items()] # `currency` field reqd for filtering
            db = client.coin_latest
            db.coin_latest.delete_many({})
            db.coin_latest.insert_many(coinvals)
            print(f'{len(coinvals)} coin values updated')

bot = commands.Bot(command_prefix='!')
bot.add_cog(Scheduler(bot))

class CoinNotFound(CommandError):
    def __init__(self, *args, **kwargs):
        self.msg = '''CoinNotFound error message: try again nerd'''
        super().__init__(*args, **kwargs)

@bot.event
async def on_ready():
    print(f'{bot.user} has connected to these guilds:{bot.guilds}')
    msg = Embed(title=":information_source: Discoin updated to v1.3.1",
        description=f'''Changelog: \n 
    • "Live" coin prices are now updated every 5 minutes. `!coin` uses this cached data, to be more friendly to the coingecko API.
    ''')

@bot.command(name="cryptohelp")
async def cryptohelp(ctx):
    msg = Embed(title=":information_source:  Discoin Help",
        description=f'''Commands: (italics args optional) I usually respond in a private message.
        • **`!buy [amount of crypto] [cryptocurrency] [$USD paid]`** *`[YYYY-MM-DD]`* add a purchase to your portfolio. if no date is provided, today's date will be used.
        • **`!sell [amount of crypto] [cryptocurrency] [$USD paid]`** *`[YYYY-MM-DD]`* add a sale to your portfolio. if no date is provided, today's date will be used.
        • **`!coin`** pm you your portfolio
        • **`!flex [user]`** flex on the boys. tag a boy to flex on him
        • **`!search [coin]`** search list of supported coins; symbols (`eth`, `btc`) give the best results
        • **`!market [coin] [# days]`** display coin performance starting from N days ago
        • **`!compare [coin1] [coin2] [# days]`** display two coins' performance starting from N days ago
        • **`!txns`** *`[cryptocurrency]`* show all your txns; or show those with a specific coin
        • **`!delete [transaction id]`** remove one of your txns by id; use `!txns` first
        • **`!export`** pm you your data in JSON format
        • **`!wipe`** remove all your data from this bot
        • **`!discoindev [message]`** send a message to the devs

         [Want me in your server? Click here](https://discord.com/api/oauth2/authorize?client_id=907807464441909289&permissions=139586882624&scope=bot%20applications.commands)

        Discoin v1.3.1
        Support my work:
        [Ko-fi](https://ko-fi.com/eulaly)
        Litecoin ||`ltc1qqcmyulnyx97a2sx4q9n3gmxqctgyg09y37ljsg`||
        Market data powered by CoinGecko
        ''',
        color=Color.orange())
    print(len(msg))
    await ctx.send(embed=msg)
    # await ctx.author.send(embed=msg)

@bot.command(name="buy")
async def _buy(ctx, amount, currency, price, date=None):
    '''add a purchase to your portfolio. if no date is provided, today's date will be used.'''
    r = requests.get('https://api.coingecko.com/api/v3/coins/'+currency)
    if not r.status_code == 200:
        coinList = search_coins(currency)
        msg = '''Coin not found. Did you mean one of these?
    • `!buy` and `!sell` use coin **`id`** (no caps, use dashes instead of spaces)
    • comparison arguments need **`symbol`**
    Try **`!search [coin name]`** or check coingecko.com for the full list
    Symbol \t | \t Name \t | \t id \n'''
        for coin in coinList[:5]:
            msg+=f'```{coin.get("symbol")}\t{coin.get("name")}\t{coin.get("id")}```'
        msg+= 'Try **`!search [coin name]`** or check coingecko.com for the full list'
        await ctx.channel.send(msg)
    else:
        if not date:
            date = dt.datetime.today().strftime('%Y-%m-%d')
        txn = {
            'amount': float(amount),
            'currency': currency,
            'price': float(price),
            'date': date,
            'userid':str(ctx.author.id)
            }
        db = client.txns
        db.txns.insert_one(txn)
        await ctx.message.add_reaction('✅')
        await ctx.author.send(f'{ctx.author.name} bought {amount} {currency} for {price} USD')

@bot.command(name="sell")
async def _sell(ctx, amount, currency, price, date=None):
    '''add a sale to your portfolio. if no date is provided, today's date will be used.'''
    await _buy(ctx=ctx, amount=-1*float(amount), currency=currency, price=-1*float(price), date=date)

@bot.command(name="coin")
async def _coin(ctx, flex=None, vs=None):
    '''pm you your portfolio'''
    db = client.txns
    userTxns = [x for x in db.txns.find({'userid':str(ctx.author.id)})]
    if not userTxns:
        msg = "No orders found. Add crypto purchases to your portfolio with: ```!txn {amount of crypto} {cryptocurrency} {$USD paid}```"
        embed = None
    else:
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
        chartfile = File("chart.png") if get_quickchart_img(roiChart) else None
        
        embed = Embed(title=f':coin:  {ctx.author.name}\'s Portfolio: ${pv} \n {roi}% ROI for ${invested} invested \n ${profit} realized',
            description=desc, color=Color.dark_gold(), type='rich')
        embed.set_image(url=f'attachment://chart.png')

        if flex:
            await ctx.channel.send(flex, embed=embed, file=chartfile)
            return
        msg = ''
    await ctx.author.send(msg, embed=embed, file=chartfile)

@bot.command(name="flex")
async def _flex(ctx, target: Member=None):
    '''flex on the boys. tag a boy to flex on him'''
    if blocked(user=(ctx.author.name+'#'+ctx.author.discriminator), type='flex'):
        return
    if target:
        msg = f'{ctx.author.mention} 💪FLEXED💪 ON {target.mention}'
    else:
        msg = f'{ctx.author.mention} 💪FLEXED💪 ON ALL YOU FOOLS! TIME TO SELL'
    await _coin(ctx=ctx, flex=msg)
@_flex.error
async def flex_error(ctx, error):
    msg = f'''{ctx.author.mention} 💪FLEXED💪 ON {ctx.author.mention}\'s OWN SELF!! 
    😤 BOO THIS MAN!! HE PROBABLY HEDGES WITH 💰FIAT💰'''
    await _coin(ctx=ctx, flex=msg)

@bot.command(name="search")
async def _search(ctx, keyword):
    '''search for supported coins. favors symbol'''
    coinList = search_coins(keyword=keyword)
    msg = f'''Here are the first 10 results for `{keyword}`: \nSymbol \t | \t Name \t | \t id'''
    for coin in coinList[:10]:
        msg+=f'''```{coin.get("symbol")}\t{coin.get("name")}\t{coin.get("id")}```'''
    msg+= '''• Remember to use the `id` explicitly for `!buy`, `!sell`, `!market`, and `!compare`'''
    if not coinList:
        msg = '''No results. Try again, or check coingecko.com.'''
    await ctx.channel.send(msg)

@bot.command(name="market")
async def _market(ctx, coin_id, days='90', vs='usd'):
    '''get data for x'''
    coin = dbck(coin_id).get('id')
    data = coin_market(coin, days=days)
    #error handling for `/market_chart` which returns 200 json() without 'market_data' if date is too old
    if data.get('error') == True:
        await ctx.channel.send(f'Rerunning with oldest available date ({days} days ago)')
        days = data.get('oldest')
        data = coin_market(coin,days=days)
    coinval_date = coin_hist(coin, days=days)
    print(type(coinval_date), coinval_date)
    print(type(data), data.get('values'))
    chart = {'chart':{'type':'line', 'data':{
        'labels':data.get('dates'),
        'datasets':[{'label':coin,'data':data.get('values'),'borderWidth':1, 'pointRadius':1, 'fill': 'False'}],
        }},
        'backgroundColor':'#2f3136',
        }
    chartfile = File("chart.png") if get_quickchart_img(chart) else None
    emb = Embed(title=f'{coin} % change since {data.get("dates")[0]}',
        description=f'{coin}: {round(data.get("values")[-1],4)}% from {round(coinval_date,2)} {vs} to {round(data.get("current"),2)}', type='rich')
    emb.set_image(url=f'attachment://chart.png')
    await ctx.channel.send(embed=emb,file=chartfile)
@_market.error
async def _market_error(ctx, error):
    print('error')
    if isinstance(error, CoinNotFound):
        await ctx.channel.send(error.msg)

@bot.command(name="compare")
async def _compare(ctx, id1, id2, days='90'):
    # try up to x coins, if ValueError that should be the date, else days=90
    '''compare performance of 2 coin_ids over X days'''
    c1 = dbck(id1)
    c2 = dbck(id2)
    c1market = coin_market(c1.get('id'), days=days)
    c2market = coin_market(c2.get('id'), days=days)
    #error handling for `/market_chart` which returns 200 json() without 'market_data' if date is too old
    if c1market.get("oldestDate") != c2market.get("oldestDate"): 
        days = min([c1market.get("oldest"),c2market.get("oldest")])
        await ctx.channel.send(f'Rerunning with oldest available date ({days} days ago)')
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
    chartfile = File("chart.png") if get_quickchart_img(chart) else None
    emb = Embed(title=f'{id1} vs {id2} relative % change since {c1market.get("dates")[0]}',
        description=f'{id1}: {round(c1market.get("values")[-1],4)}% from ${"{:,.2f}".format(c1date)} to ${round(c1market.get("current"),2)}\n \
            {id2}: {round(c2market.get("values")[-1],4)}% from ${"{:,.2f}".format(c2date)} to ${round(c2market.get("current"),2)}', type='rich') 
    emb.set_image(url=f'attachment://chart.png')
    await ctx.channel.send(embed=emb,file=chartfile)
@_compare.error
async def _compare_error(ctx, error):
    if isinstance(error, CoinNotFound):
        print(error.msg)
        await ctx.channel.send(error.msg)

@bot.command(name="txns")
async def _txns(ctx, coin=None):
    '''find all your txns with a specific coin'''
    db = client.txns
    searchTerms = {'userid':str(ctx.author.id)}
    if coin:
        searchTerms['currency'] = coin
    data = [x for x in db.txns.find(searchTerms)]
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
        await ctx.author.send(msg)
        msg = ""

@bot.command(name="delete")
async def _delete(ctx, txnid):
    '''remove a txn from your orders by id'''
    db = client.txns
    db.txns.delete_one({'_id':ObjectId(txnid), 'userid':str(ctx.author.id)})
    await ctx.message.add_reaction('✅')

@bot.command(name="export")
async def _export(ctx):
    '''pm you your data in JSON format'''
    auth = str(ctx.author.id)
    db = client.txns
    data = [x for x in db.txns.find({'userid':auth})]
    for d in data:
        d['_id'] = str(d.get('_id'))
    export = {'txns':data}
    with open(f'{auth}.json', 'w', encoding='utf-8') as f:
        json.dump(export, f, indent=4, ensure_ascii=False, separators=(',', ':'), sort_keys=True)
    await ctx.author.send(file=File(f'{auth}.json'))
    await ctx.message.add_reaction('✅')

@bot.command(name="wipe")
async def _wipe(ctx):
    '''remove all your data from this bot'''
    db = client.txns
    db.txns.delete_many({'userid':str(ctx.author.id)})
    ck = [x for x in db.txns.find({'userid': str(ctx.author.id)})]
    if len(ck) == 0:
        await ctx.message.add_reaction('✅')
        await ctx.author.send('nice knowing you')
    else:
        await ctx.author.send('Something went wrong.')



## Dev Commands

@bot.command(name="discoindev")
async def _contactdev(ctx):
    '''send a message to the devs'''
    if blocked(user=(ctx.author.name+'#'+ctx.author.discriminator), type='dev'):
        return
    embed = Embed(title=f'🔧 Dev Message from {ctx.author.name}#{ctx.author.discriminator}', type='rich',
        description=f'{ctx.author.display_name} ({ctx.author.id}) from {ctx.message.guild} says: {ctx.message.content}',
        color=Color.blue())
    devch = bot.get_channel(456908681330688000)
    await devch.send(None, embed=embed)
@_contactdev.error
async def dev_error(ctx, error):
    if isinstance(error, commands.errors.CommandOnCooldown):
        await ctx.channel.send(f'{ctx.author.display_name} please try again later')

@bot.command(name="ddev")
async def _ddev(ctx):
    if not ctx.author.id == 126768317024305152:
        await ctx.message.add_reaction('🛑')
        return
    else:
        msg = f'''
        • **`!devblock [userid] [type]`** userid is a name, type = flex or /
        '''
    await ctx.author.send(msg)

def blocked(user: str, type: str) -> bool:
    db = client.blocked
    blocked = [x for x in db.blocked.find({'userid':user, 'type':type})]
    return True if blocked else False

@bot.command(name="devblock")
async def _devblock(ctx, userid, kw):
    if not ctx.author.id == 126768317024305152:
        await ctx.message.add_reaction('🛑')
        return
    else:
        db = client.blocked
        db.blocked.insert_one({'user':userid, 'type':kw})
        await ctx.message.add_reaction('✅')

@bot.command(name="devunblock")
async def _devblock(ctx, userid, kw):
    if not ctx.author.id == 126768317024305152:
        await ctx.message.add_reaction('🛑')
        return
    else:
        db = client.blocked
        db.blocked.delete_one({'user':userid, 'type':kw})
        await ctx.message.add_reaction('✅')

bot.run(getenv('api_token'))