FROM wheelhouse-lab-base
RUN apt-get update -qq && apt-get install -y -qq --no-install-recommends nginx \
 && rm -rf /var/lib/apt/lists/* && rm -f /etc/nginx/sites-enabled/default
COPY orders.conf /etc/nginx/conf.d/orders.conf
