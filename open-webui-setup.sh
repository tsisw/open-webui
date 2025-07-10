export VIRTUAL_ENV=tsi-openwebui
if [ -e open-webui ]
then
echo "opep-webui exists"
else
git clone git@github.com:tsisw/open-webui.git
fi
cd open-webui/
pip install uv
uv venv tsi-openwebui
source tsi-openwebui/bin/activate
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.7/install.sh | bash
deactivate
source tsi-openwebui/bin/activate
uv pip install -r backend/requirements.txt
pip install npm
sudo apt install npm
node -v
npm -v
nvm install 20.18.1
nvm use 20.18.1
uv run open-webui serve

