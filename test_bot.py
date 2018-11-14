from bot import IndraBot
bot = IndraBot()

ret = bot.handle_question('does MEK regulate ERK?')
assert ret['stmts']
ret = bot.handle_question('how does MEK regulate ERK?')
assert ret['stmts']
ret = bot.handle_question('does PTPN11 regulate RASA1?')
assert ret['stmts']
ret = bot.handle_question('does KDM1 demethylate TP53?')
assert ret['stmts']
ret = bot.handle_question('what genes does EGR1 activate?')
assert ret['stmts']
ret = bot.handle_question('what forms of STAG2 are active?')
assert ret['stmts']
