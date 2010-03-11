###
# Copyright (c) 2010, Daniel Folkinshteyn
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
#   * Redistributions of source code must retain the above copyright notice,
#     this list of conditions, and the following disclaimer.
#   * Redistributions in binary form must reproduce the above copyright notice,
#     this list of conditions, and the following disclaimer in the
#     documentation and/or other materials provided with the distribution.
#   * Neither the name of the author of this software nor the name of
#     contributors to this software may be used to endorse or promote products
#     derived from this software without specific prior written consent.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
# ARE DISCLAIMED.  IN NO EVENT SHALL THE COPYRIGHT OWNER OR CONTRIBUTORS BE
# LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
# CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
# SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
# INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
# CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
# ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.

###

import supybot.utils as utils
from supybot.commands import *
import supybot.plugins as plugins
import supybot.ircutils as ircutils
import supybot.callbacks as callbacks

import supybot.conf as conf
import supybot.ircdb as ircdb

import re
import os
import time

try:
    import sqlite
except ImportError:
    raise callbacks.Error, 'You need to have PySQLite installed to use this ' \
                           'plugin.  Download it at ' \
                           '<http://code.google.com/p/pysqlite/>'


class MessageParser(callbacks.Plugin, plugins.ChannelDBHandler):
    """This plugin can set regexp triggers to activate the bot.
    Use 'add' command to add regexp trigger, 'remove' to remove."""
    threaded = True
    def __init__(self, irc):
        callbacks.Plugin.__init__(self, irc)
        plugins.ChannelDBHandler.__init__(self)
    
    def makeDb(self, filename):
        if os.path.exists(filename):
            return sqlite.connect(filename)
        db = sqlite.connect(filename)
        cursor = db.cursor()
        cursor.execute("""CREATE TABLE triggers (
                          id INTEGER PRIMARY KEY,
                          regexp TEXT UNIQUE ON CONFLICT REPLACE,
                          added_by TEXT,
                          added_at TIMESTAMP,
                          usage_count INTEGER,
                          action TEXT,
                          locked BOOLEAN
                          )""")
        db.commit()
        return db
    
    def _updateRank(self, channel, regexp):
        if self.registryValue('keepRankInfo', channel):
            db = self.getDb(channel)
            cursor = db.cursor()
            cursor.execute("""SELECT usage_count
                      FROM triggers
                      WHERE regexp=%s""", regexp)
            old_count = cursor.fetchall()[0][0]
            cursor.execute("UPDATE triggers SET usage_count=%s WHERE regexp=%s", old_count + 1, regexp)
            db.commit()
    
    def doPrivmsg(self, irc, msg):
        channel = msg.args[0]
        if not irc.isChannel(channel):
            return
        if self.registryValue('enable', channel):
            actions = []
            db = self.getDb(channel)
            cursor = db.cursor()
            cursor.execute("SELECT regexp, action FROM triggers")
            if cursor.rowcount == 0:
                return
            for (regexp, action) in cursor.fetchall():
                match = re.search(regexp, msg.args[1])
                if match is not None:
                    self._updateRank(channel, regexp)
                    for (i, j) in enumerate(match.groups()):
                        action = re.sub(r'\$' + str(i+1), match.group(i+1), action)
                    actions.append(action)
            
            if len(actions) > 0:
                irc.replies(actions, prefixNick=False)

            #if re.search('some stuff', msgtext):
            #    irc.reply('some stuff detected', prefixNick=False)
    
    def add(self, irc, msg, args, channel, regexp, action):
        """[<channel>] <regexp> <action>

        Associates <regexp> with <action>.  <channel> is only
        necessary if the message isn't sent on the channel
        itself.  Action is echoed upon regexp match, with variables $1, $2, 
        etc. being interpolated from the regexp match groups."""
        db = self.getDb(channel)
        cursor = db.cursor()
        cursor.execute("SELECT id, locked FROM triggers WHERE regexp=%s", regexp)
        if cursor.rowcount != 0:
            (id, locked) = map(int, cursor.fetchone())
        else:
            locked = False
        #capability = ircdb.makeChannelCapability(channel, 'factoids')
        if not locked:
            if ircdb.users.hasUser(msg.prefix):
                name = ircdb.users.getUser(msg.prefix).name
            else:
                name = msg.nick
            cursor.execute("""INSERT INTO triggers VALUES
                              (NULL, %s, %s, %s, %s, %s, %s)""",
                           regexp, name, int(time.time()), 0, action, 0)
            db.commit()
            irc.replySuccess()
        else:
            irc.error('That trigger is locked.')
    add = wrap(add, ['channel', 'something', 'something'])
    
    def remove(self, irc, msg, args, channel, regexp):
        """[<channel>] <regexp>]

        Removes the trigger for <regexp> from the triggers database.  
        <channel> is only necessary if
        the message isn't sent in the channel itself.
        """
        db = self.getDb(channel)
        cursor = db.cursor()
        cursor.execute("SELECT id, locked FROM triggers WHERE regexp=%s", regexp)
        if cursor.rowcount != 0:
            (id, locked) = map(int, cursor.fetchone())
        else:
            irc.error('There is no such regexp trigger.')
        
        if locked:
            irc.error('This regexp trigger is locked.')
        
        cursor.execute("""DELETE FROM triggers WHERE id=%s""", id)
        db.commit()
        irc.replySuccess()
    remove = wrap(remove, ['channel', 'something'])

    def show(self, irc, msg, args, channel, regexp):
        """[<channel>] <regexp>

        Looks up the value of <regexp> in the triggers database.
        <channel> is only necessary if the message isn't sent in the channel 
        itself.
        """
        db = self.getDb(channel)
        cursor = db.cursor()
        cursor.execute("SELECT regexp, action FROM triggers WHERE regexp=%s", regexp)
        if cursor.rowcount != 0:
            (regexp, action) = cursor.fetchone()
        else:
            irc.error('There is no such regexp trigger.')
            
        irc.reply("The trigger for regexp '%s' is '%s'" % (regexp, action))
    show = wrap(show, ['channel', 'something'])

    def listall(self, irc, msg, args, channel):
        """[<channel>]

        Lists regexps present in the triggers database.
        <channel> is only necessary if the message isn't sent in the channel 
        itself.
        """
        db = self.getDb(channel)
        cursor = db.cursor()
        cursor.execute("SELECT regexp FROM triggers")
        if cursor.rowcount != 0:
            regexps = cursor.fetchall()
        else:
            irc.error('There is no available regexp triggers.')
        
        s = [ regexp[0] for regexp in regexps ]
        irc.reply("'" + "','".join(s) + "'")
    listall = wrap(listall, ['channel'])

    def triggerrank(self, irc, msg, args, channel):
        """[<channel>]
        
        Returns a list of top-ranked regexps, sorted by usage count 
        (rank). The number of regexps returned is set by the 
        rankListLength registry value. <channel> is only necessary if the 
        message isn't sent in the channel itself.
        """
        numregexps = self.registryValue('rankListLength', channel)
        db = self.getDb(channel)
        cursor = db.cursor()
        cursor.execute("""SELECT regexp, usage_count
                          FROM triggers
                          ORDER BY usage_count DESC
                          LIMIT %s""", numregexps)
        regexps = cursor.fetchall()
        s = [ "#%d %s (%d)" % (i+1, regexp[0], regexp[1]) for i, regexp in enumerate(regexps) ]
        irc.reply(", ".join(s))
    triggerrank = wrap(triggerrank, ['channel'])


Class = MessageParser


# vim:set shiftwidth=4 softtabstop=4 expandtab textwidth=79: