from bot import IndraBot
bot = IndraBot()

stmts = bot.handle_question('does MEK regulate ERK?')
assert stmts
stmts = bot.handle_question('how does MEK regulate ERK?')
assert stmts
stmts = bot.handle_question('does PTPN11 regulate RASA1?')
assert stmts
stmts = bot.handle_question('does KDM1 demethylate TP53?')
assert stmts is not None
stmts = bot.handle_question('what genes does EGR1 activate?')
assert stmts is not None
