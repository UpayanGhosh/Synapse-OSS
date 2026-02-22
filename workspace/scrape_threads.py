import asyncio
import sys
from crawl4ai import AsyncWebCrawler

async def main():
    url = "https://www.threads.net/@talonhayess/post/DU_DKLfktBv"
    async with AsyncWebCrawler() as crawler:
        result = await crawler.arun(url=url)
        if result.success:
            print(result.markdown)
        else:
            print(f"Error: {result.error_message}")

if __name__ == "__main__":
    asyncio.run(main())
