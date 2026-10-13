-- Run from 3ds Max > Scripting > Run Script, or drag this file into a viewport.
(
    local root = getFilenamePath (getSourceFileName())
    python.ExecuteFile (root + "install_maxcraft.py")
    messageBox "MaxCraft installed. Run launch_maxcraft.py to open the panel, or add the MaxCraft action to a toolbar." title:"MaxCraft"
)

