This is a [Next.js](https://nextjs.org) project bootstrapped with [`create-next-app`](https://nextjs.org/docs/app/api-reference/cli/create-next-app).

## Getting Started

First, run the development server:

```bash
npm run dev
# or
yarn dev
# or
pnpm dev
# or
bun dev
```

Open [http://localhost:3000](http://localhost:3000) with your browser to see the result.

You can start editing the page by modifying `app/page.tsx`. The page auto-updates as you edit the file.

This project uses [`next/font`](https://nextjs.org/docs/app/building-your-application/optimizing/fonts) to automatically optimize and load [Geist](https://vercel.com/font), a new font family for Vercel.

## Learn More

To learn more about Next.js, take a look at the following resources:

- [Next.js Documentation](https://nextjs.org/docs) - learn about Next.js features and API.
- [Learn Next.js](https://nextjs.org/learn) - an interactive Next.js tutorial.

You can check out [the Next.js GitHub repository](https://github.com/vercel/next.js) - your feedback and contributions are welcome!

## Deploy on Vercel

The easiest way to deploy your Next.js app is to use the [Vercel Platform](https://vercel.com/new?utm_medium=default-template&filter=next.js&utm_source=create-next-app&utm_campaign=create-next-app-readme) from the creators of Next.js.

Check out our [Next.js deployment documentation](https://nextjs.org/docs/app/building-your-application/deploying) for more details.


+------------------+--------------------------------------------------+--------------------------------------+
|  Sidebar (左)    |             Main Chat Area (中)                  |          Agent Inspector (右)        |
+------------------+--------------------------------------------------+--------------------------------------+
| [Logo] Avatar    |                                                  | [Tab: 规划图] [Tab: 状态] [Tab: 日志] |
|                  |  User: 帮我把桌面上的财报数据整理成 Excel          |                                      |
| [New Chat +]     |                                                  |            (O) Start                 |
|                  |  Agent: 好的，正在规划任务...                      |             |                        |
| > History        |                                                  |             v                        |
| - 整理财报       |  [Thinking...]                                   |        [ 🔍 扫描文件 ] (Running)      |
| - 每日简报       |  > 已生成执行计划 (点击查看详情)                   |             |                        |
| - 服务器巡检     |                                                  |             v                        |
|                  |  Agent: 发现 3 个 CSV 文件。                     |        [ 🐍 数据清洗 ] (Pending)      |
| [Settings ⚙️]    |  正在执行数据清洗...                             |             |                        |
|                  |                                                  |             v                        |
|                  |  ----------------------------------------------  |        [ 💾 保存 Excel] (Pending)     |
|                  |  |  ⚠️ Human Approval Needed                  |  |                                      |
|                  |  |  是否允许删除原始 CSV 文件?                |  |  ----------------------------------  |
|                  |  |  [ 允许 ]   [ 拒绝 ]                       |  |  Current Context:                    |
|                  |  ----------------------------------------------  |  {                                   |
|                  |                                                  |    "files": ["a.csv", "b.csv"],      |
|                  |  Agent: 任务完成。文件已保存至 /Output。          |    "retry_count": 0                  |
|                  |                                                  |  }                                   |
+------------------+--------------------------------------------------+--------------------------------------+
