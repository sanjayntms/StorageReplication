# StorageReplication
  ## On Linux VM, open port 3000, run
  * sudo apt update
  * sudo apt install python3-pip
  * sudo apt update
  * sudo apt install python3 python3-pip -y # For Ubuntu
  * sudo apt install python3-venv -y
  * python3 -m venv venv
  * source venv/bin/activate
  * pip install flask requests
  * pip install azure-storage-blob
  * python3 app.py
  
* export AZURE_STORAGE_ACCOUNT_NAME="ntmssaudk"
* export AZURE_STORAGE_ACCOUNT_KEY="h4VSPgMtElJ/DGw/vBdd9qxo+AsUU2Xd2BLNnXahioRbzaSMhXbg5s9D5XIgGbyzQgbrEC6r2x81+ASt9fk3EA=="
* export AZURE_STORAGE_CONTAINER_NAME="media"
* export FLASK_SECRET_KEY="something-secret"
* export AZURE_RESOURCE_GROUP="Linux-RG"
# Create RAGRS storage account and update the above value.
