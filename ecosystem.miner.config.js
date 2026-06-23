module.exports = {
  apps: [{
    name: "minos-miner",
    script: "./start-miner.sh",
    interpreter: "bash",
    cwd: "/root/draven/minos_subnet",
    autorestart: true,
    max_restarts: 10,
    restart_delay: 30000,
    kill_timeout: 15000,
    log_date_format: "YYYY-MM-DD HH:mm:ss Z",
    env: { PYTHONUNBUFFERED: "1" },
  }]
};
