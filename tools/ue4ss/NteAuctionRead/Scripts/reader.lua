-- Read only the current auction/result UI. Called on the existing game thread.
local source = debug.getinfo(1, "S").source:gsub("^@", "")
local dir = source:match("^(.*[/\\])") or "./"
local round = dofile(dir .. "round.lua")
local function get(fn) local ok, v = pcall(fn); if ok then return v end end
local function valid(o) return get(function() return o ~= nil and o:IsValid() end) == true end
local function visible(o)
    if not valid(o) then return false end
    local seen = {}
    while valid(o) do
        local name = o:GetFullName()
        if seen[name] then return false end
        seen[name] = true
        if not o:IsVisible() then return false end
        local parent = o:GetParent()
        if not valid(parent) then
            -- A nested UserWidget's root has no panel parent. Its owning
            -- UserWidget may still be collapsed (cached default bid text).
            local tree = o:GetOuter()
            if valid(tree) and tree:IsA("/Script/UMG.WidgetTree") then
                local owner = tree:GetOuter()
                if valid(owner) and owner:IsA("/Script/UMG.UserWidget") then parent=owner end
            end
        end
        o = parent
    end
    return true
end
local function str(v) if type(v) == "string" then return v end; return v:ToString() end
local function array(v, returned)
    local a = {}
    for i = 1, #v do
        -- This fixed UE4SS build returns UFunction array elements as
        -- RemoteUnrealParam (LuaUObject.cpp GetNonTrivialLocal/GetParam).
        -- Property-backed TArrays already return their values directly.
        a[i] = returned and v[i]:get() or v[i]
    end
    return a
end
local function text(o, name)
    return get(function()
        local c = o:GetPropertyValue(name)
        if visible(c) then return str(c:GetText()) end
    end)
end
local function current(class)
    local found = {}
    for _, o in ipairs(FindAllOf(class) or {}) do
        if valid(o) and not o:GetFullName():find("Default__", 1, true) and visible(o) then found[#found+1] = o end
    end
    if #found == 1 then return found[1] end
end
local function walk(o, visit, seen)
    if not visible(o) then return end
    local name = o:GetFullName()
    if seen[name] then return end
    seen[name] = true
    visit(o, name)
    if o:IsA("/Script/UMG.UserWidget") then
        local root = get(function() return o:GetPropertyValue("WidgetTree"):GetPropertyValue("RootWidget") end)
        if root then walk(root, visit, seen) end
    elseif o:IsA("/Script/UMG.PanelWidget") then
        for i = 0, o:GetChildrenCount()-1 do walk(o:GetChildAt(i), visit, seen) end
    end
end
local function info_from(model)
    local direct = get(function() return {infoID=str(model:GetPropertyValue("InfoID")), field="InfoID"} end)
    if direct then return direct end
    local found = {}
    local cls = model:GetClass()
    while valid(cls) do
        cls:ForEachProperty(function(p)
            if p:GetFullName():match("^StructProperty ") then
                local name = p:GetFName():ToString()
                local v = get(function()
                    local row = model:GetPropertyValue(name)
                    return {infoID=str(row.InfoID), params=array(row.Params), field=name .. ".InfoID/Params"}
                end)
                if v then found[#found+1]=v end
            end
        end)
        cls = cls:GetSuperStruct()
    end
    if #found == 1 then return found[1] end
end
local function configuration(id)
    for _, asset in ipairs(FindAllOf("BidKingDataAsset") or {}) do
        if valid(asset) and not asset:GetFullName():find("Default__", 1, true) then
            local explanation = get(function()
                local dt = asset:GetPropertyValue("BidKingInfoConfigDataTable")
                if not valid(dt) then return end
                local row = dt:FindRow(id)
                if row then return {table=dt:GetFullName(), row=id, title=str(row.InfoTitle),
                    displayText=str(row.DisplayText), infoType=array(row.InfoType), qualityType=array(row.InfoParams.QualityType)} end
            end)
            if explanation then return explanation end
        end
    end
end
return function()
    local result = current("HTUI_BidKingResultForm")
    local state, name, raw, ui = round()
    local out = {scene="NONE", texts={}, cards={}, seats={}, errors={}}
    if result then ui=result; out.scene="SETTLEMENT"
    elseif state == "VALUE" then out.scene="IN_AUCTION"; out.curRoundIndex=raw
    else return out end
    out.instance = ui:GetFullName()
    local card_widgets = {}
    walk(ui, function(o, n)
        if o:IsA("/Script/UMG.TextBlock") or o:IsA("/Script/UMG.RichTextBlock") then
            local value = get(function() return str(o:GetText()) end)
            if value and value ~= "" then out.texts[#out.texts+1]={instance=n,text=value} end
        end
        if o:IsA("/Script/HTGame.HTUI_BidKingInfoListItem") then card_widgets[n]=o end
    end, {})
    if out.scene == "IN_AUCTION" then
        local list = get(function() return ui:GetPropertyValue("ListViewInfo") end)
        local models = {}
        if visible(list) then
            local all = get(function() return array(list:GetPropertyValue("ListItems")) end) or {}
            for _, model in ipairs(all) do
                if valid(model) and model:IsA("/Script/HTGame.HTListObject") then
                    local w = model:GetPropertyValue("RelateWidget")
                    if visible(w) and w:IsA("/Script/HTGame.HTUI_BidKingInfoListItem") then
                        models[w:GetFullName()]=model; card_widgets[w:GetFullName()]=w
                    end
                end
            end
            local shown = get(function() return array(list:GetDisplayedEntryWidgets(), true) end)
            if shown then
                out.cardsReadable=true
                for _, w in ipairs(shown) do
                    if visible(w) and w:IsA("/Script/HTGame.HTUI_BidKingInfoListItem") then
                        card_widgets[w:GetFullName()]=w
                    else out.cardsReadable=false end
                end
            end
        end
        local cache = get(function()
            local pc=ui:GetOwningPlayer()
            local player=pc:GetPropertyValue("Player")
            if not valid(player) or not player:IsA("/Script/Engine.LocalPlayer") then return end
            local ps=pc:GetPropertyValue("PlayerState")
            if valid(ps) and ps:IsA("/Script/HTGame.HTPlayerState") then
                return {name=ps:GetFullName(),rows=ps:GetPropertyValue("InfoCacheArray")}
            end
        end)
        if cache then out.playerState=cache.name end
        for n, widget in pairs(card_widgets) do
            local title, content = text(widget,"TextTitle"), text(widget,"TextContent")
            if content and content ~= "" then
                local card={instance=n,title=title,content=content,numberSource="FORMATTED_UI_TEXT"}
                local model=models[n]
                local info=model and get(function() return info_from(model) end)
                if info then
                    card.model=model:GetFullName(); card.boundField=info.field; card.infoID=info.infoID
                    card.boundParams=info.params; card.config=configuration(info.infoID)
                    if cache then
                        local matches={}
                        for i=1,#cache.rows do
                            local row=cache.rows[i]
                            if str(row.InfoID)==info.infoID then matches[#matches+1]={indexZero=i-1,params=array(row.Params)} end
                        end
                        card.cacheMatches=matches
                    end
                else card.bindingStatus="INFO_ID_NOT_AVAILABLE_ON_BOUND_MODEL" end
                out.cards[#out.cards+1]=card
            else out.cardsReadable=false end
        end
        table.sort(out.cards,function(a,b) return a.instance<b.instance end)
        local players=get(function() return ui:GetPropertyValue("VerticalBoxPlayer") end)
        if players then
            walk(players,function(o,n)
                if o:IsA("/Script/HTGame.HTUI_BidKingCloneBidSlot") then
                    local mine=get(function() return o:GetPropertyValue("ImageMineFlag") end)
                    -- Field evidence showed TextBidMoney retaining the same
                    -- designer default on all four seats while no bid was
                    -- displayed. Keep the existing bid reader in charge until
                    -- the actual round-cell binding is established.
                    out.seats[#out.seats+1]={slot=#out.seats+1,instance=n,name=text(o,"TextPlayerName"),
                        rawBidText=text(o,"TextBidMoney"), observedRoundIndex=raw,
                        isMe=valid(mine) and mine:IsVisible() or nil}
                end
            end,{})
        end
    else
        out.bill={instance=out.instance,winner=text(ui,"TextPlayerName"),bidText=text(ui,"TextBidMoney"),
            valueText=text(ui,"TextValue"),incomeText=text(ui,"TextIncome"),rewardText=text(ui,"TextRewardMoney"),gradeText=text(ui,"TextEvaluate")}
        local wh=get(function() return ui:GetPropertyValue("UI_BidKingWarehouse") end)
        if valid(wh) then
            local kind=wh:GetPropertyValue("WarehouseType")
            if kind==1 then
                out.settlementList={instance=wh:GetFullName(),warehouseType=kind,completeness="UNKNOWN",slots={}}
                local slots=get(function() return array(wh:GetPropertyValue("SettleSlots")) end)
                local cached=get(function() return array(wh:GetPropertyValue("CacheWarehouseSlotArray")) end)
                out.settlementList.settleSlotArrayCount=slots and #slots or nil
                out.settlementList.cachedWidgetCount=cached and #cached or nil
                for _, slot in ipairs(slots or cached or {}) do
                    if visible(slot) then
                        out.settlementList.slots[#out.settlementList.slots+1]={instance=slot:GetFullName(),
                            name=text(slot,"TextBlock_ItemName"),priceText=text(slot,"TextBlock_Price")}
                    end
                end
            end
        end
    end
    return out
end
