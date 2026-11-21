PluginInfo = { Name = "No Runtime Guard", Version = "1.0", Id = "noguard", Description = "x", Author = "y" }
function GetControls(props) return { { Name = "A", ControlType = "Text", UserPin = true, PinStyle = "Output" } } end
function GetControlLayout(props) return {}, {} end
Controls.A.String = "hi"
