-- One read-only, game-thread callback. No keys, RPCs, actions or auction loop.
local source=debug.getinfo(1,"S").source:gsub("^@","")
local dir=source:match("^(.*[/\\])") or "./"
local config=dofile(dir.."config.lua")
local session=os.date("!%Y%m%dT%H%M%SZ")
local function json(v)
    local t=type(v)
    if t=="nil" then return "null" end
    if t=="boolean" or t=="number" then return tostring(v) end
    if t=="string" then
        return '"'..v:gsub('[%z\1-\31\\"]',function(c)
            return ({['"']='\\"',['\\']='\\\\',['\n']='\\n',['\r']='\\r',['\t']='\\t'})[c] or string.format('\\u%04x',string.byte(c))
        end)..'"'
    end
    local a={}
    if #v>0 or next(v)==nil then for _,item in ipairs(v) do a[#a+1]=json(item) end; return '['..table.concat(a,',')..']' end
    local keys={}; for k in pairs(v) do keys[#keys+1]=k end; table.sort(keys)
    for _,k in ipairs(keys) do a[#a+1]=json(k)..':'..json(v[k]) end
    return '{'..table.concat(a,',')..'}'
end
local function log(stage,detail)
    local line=os.date("!%Y-%m-%dT%H:%M:%SZ").." stage="..stage.." "..tostring(detail or "").."\n"
    print("[NteAuctionRead] "..line)
    local f=io.open(config.output_dir.."/runtime-"..session..".log","a"); if f then f:write(line); f:close() end
end
log("LOADED","revision=auction-read-1")
if type(ExecuteInGameThreadWithDelay)~="function" then log("ERROR","missing ExecuteInGameThreadWithDelay"); return end
local entered=false
local previous
local function poll()
    if not entered then entered=true; log("CALLBACK_ENTERED") end
    -- Reload only this read-only script so ordinary Lua fixes don't require a
    -- game restart, mod reload, changed hooks or another paid auction.
    local ok,out=xpcall(function() return dofile(dir.."reader.lua")() end,debug.traceback)
    if not ok then out={scene="NONE",errors={out}} end
    out.source="ue4ss_ui"; out.session=session
    local changes={}
    for k,v in pairs(out) do if k~="texts" then changes[k]=v end end
    changes.environmentTexts={}
    for _,row in ipairs(out.texts or {}) do
        if row.text:find("场",1,true) or row.text:find("宝箱",1,true) or row.text:find("对局",1,true) then
            changes.environmentTexts[#changes.environmentTexts+1]=row
        end
    end
    local signature=json(changes)
    if signature~=previous then log("CHANGED",signature); previous=signature end
    out.sampledAt=os.time(); out.readUtc=os.date("!%Y-%m-%dT%H:%M:%SZ")
    local f,err=io.open(config.output_dir.."/auction.json","w")
    if f then f:write(json(out)); f:close() else log("OUTPUT_ERROR",err) end
    ExecuteInGameThreadWithDelay(1000,poll)
end
ExecuteInGameThreadWithDelay(1500,poll)
log("QUEUED","api=ExecuteInGameThreadWithDelay delay_ms=1500")
