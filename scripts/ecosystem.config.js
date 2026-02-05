// PM2 Ecosystem Configuration for Next.js Apps
// Copy this to your Next.js app directory and customize as needed
//
// Usage:
//   pm2 start ecosystem.config.js
//   pm2 restart online-docs
//   pm2 logs online-docs

module.exports = {
  apps: [
    {
      name: 'online-docs',
      script: 'npm',
      args: 'start',
      cwd: '/srv/online-docs',
      instances: 1,
      autorestart: true,
      watch: false,
      max_memory_restart: '1G',
      env: {
        NODE_ENV: 'production',
        PORT: 3000
      },
      error_file: '/srv/online-docs/logs/pm2-error.log',
      out_file: '/srv/online-docs/logs/pm2-out.log',
      log_date_format: 'YYYY-MM-DD HH:mm:ss Z',
      merge_logs: true,
      time: true
    }
  ]
};
