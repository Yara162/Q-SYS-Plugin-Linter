PluginInfo = { Name = "Broken", Version = "1.0", Id = "broken", Description = "x", Author = "y" }
function GetControls(props)
    return { { Name = "A", ControlType = "Text" } }
end
function GetControlLayout(props)
    if true then
        return { A = { Position = { 0, 0 }, Size = { 10, 10 } } }, {}
end
