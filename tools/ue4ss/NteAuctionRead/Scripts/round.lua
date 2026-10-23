-- Run only inside the game-thread callback. Read no auction data except CurRoundIndex.
return function()
    local visible = {}
    for _, ui in ipairs(FindAllOf("HTUI_BidKingCloneMain") or {}) do
        if ui and ui:IsValid() then
            local name = ui:GetFullName()
            -- Exclude the class default object; hidden cached widgets are not current UI.
            if not name:find("Default__", 1, true) and ui:IsVisible() then
                visible[#visible + 1] = { object = ui, name = name }
            end
        end
    end
    if #visible == 0 then return "WAITING" end
    if #visible > 1 then
        local names = {}
        for _, candidate in ipairs(visible) do names[#names + 1] = candidate.name end
        table.sort(names)
        return "AMBIGUOUS", table.concat(names, " | ")
    end
    local candidate = visible[1]
    local ok, raw = pcall(function() return candidate.object:GetPropertyValue("CurRoundIndex") end)
    if not ok then error("CurRoundIndex read failed: instance=" .. candidate.name .. " error=" .. tostring(raw)) end
    if type(raw) ~= "number" or raw % 1 ~= 0 then
        error("CurRoundIndex is not an integer: instance=" .. candidate.name .. " type=" .. type(raw) .. " value=" .. tostring(raw))
    end
    return "VALUE", candidate.name, raw, candidate.object
end
