# IM3180
Repository for NTU IM3180: Design &amp; Innovation Project

## Quickstart:

### VSCode Python Extension Method
> In the search bar at the top middle of the window
1. Type "\> Python: Create Environment"
1. Click "Venv" for environment type
1. Click whatever Python version you have (should be fine >3.x)
1. Click "requirements.txt" for dependacies to install and give a bit
1. Kill and refresh terminal in VSCode, its working if your terminal looks like:   
```(.venv) C:\...```

### CLI Method
1. Create a python venv  
```py -m venv venv```

1. Active the venv 
```venv\Scripts\activate``` (Windows)  
```source venv/bin/activate``` (macOS/Linux)

1. Install required dependencies into venv  
```pip install -r requirements.txt```

## API Input/Output

### POST "/" 
Assume:  
JSONREsponse({  
   "addresses":[...], # order in priority   
   "hotel_address":...,   
   "service_times":[...]  
})

JSONReturn({  
    "route":{} # dict of {address:expected time}  
})