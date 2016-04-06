#!/bin/bash

# install docker
curl -fsSL https://get.docker.com/ | sh
sudo usermod -aG docker ubuntu

# download cnsmo
mkdir cnsmo
cd cnsmo
git clone https://github.com/dana-i2cat/cnsmo.git
git clone https://github.com/dana-i2cat/cnsmo-net-services.git
cd ..

# install cnsmo requirements
sudo pip install -r cnsmo/cnsmo/requirements.txt

#build new-easy-rsa docker
cd /tmp/cnsmo/cnsmo-net-services/src/main/docker/vpn/easy-rsa
docker build -t new-easy-rsa .
cd /tmp

#install redis
wget http://download.redis.io/releases/redis-3.0.7.tar.gz
tar xzf redis-3.0.7.tar.gz
rm redis-3.0.7.tar.gz
cd redis-3.0.7
make
make install --quiet
cd ..
