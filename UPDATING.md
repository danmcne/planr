# Updating planr to v1.2.1 — READ FIRST

The symptoms you saw after the previous update ("Not Found" JSON at
/calendar, month view still blank, old date pickers) are exactly what a
**mixed-version install** produces:

* "Not Found" JSON at a URL the new code serves → the **old server process
  was still running** (Python does not hot-reload; `main.py` changes need a
  restart).
* Month view blank → the **old `static/js/month.js`** (which has a fatal
  SyntaxError) was still on disk and/or cached by the browser. Unzipping
  *adds and overwrites* files but never deletes removed ones.

## Clean update procedure

```sh
sudo systemctl stop planr            # 1. stop the running server

cd /path/to/planr
rm -rf routers static templates      # 2. remove old code dirs (NOT your data:
rm -f  *.py                          #    the DB and notes/journal dirs live
                                     #    under ~/.planr and are untouched)

unzip /path/to/planr-1.2.1.zip -d .  # 3. unpack the new version

sudo systemctl start planr           # 4. restart

# 5. In the browser: hard refresh (Ctrl+Shift+R) on every open planr tab,
#    or clear site data for localhost:8000 — JS modules are cached hard.
```

Sanity check after restarting: `curl localhost:8000/day` should return HTML,
and the page footer scripts should reference `/static/js/cal-common.js`
(new in this version). If `/day` returns JSON "Not Found", the old process
is still bound to the port.

## What changed (v1.2.1)

See CHANGES-1.2.1.md.
