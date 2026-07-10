
# exec(open("c:/Git_repos/Kicad_projects/Microwave_Beamer/Scripting/selector.py").read())
# exec(open("c:/Git_repos/Kicad_projects/Microwave_Beamer/Scripting/selector.py").read())
import pcbnew
board = pcbnew.GetBoard()

for track in board.GetTracks():
    track.ClearSelected()
    track.ClearBrightened()
    

    if isinstance(track, pcbnew.PCB_TRACK):
        width_mm = track.GetWidth() / 1e6
        
        class_name = str(track.GetNetClassName())


        CONDITION = width_mm <= 0.15 
        # and class_name == "Default":


        if CONDITION:
            track.SetSelected()
            track.SetBrightened()

pcbnew.Refresh()
print("done")