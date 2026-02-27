import asyncio
import sys

if sys.platform == "win32":
    print("[scrape_threads] This script uses crawl4ai which is not available on Windows.")
    print("                 On Windows, use the /browse endpoint via Playwright instead.")
    sys.exit(1)

from crawl4ai import AsyncWebCrawler  # only reached on Mac/Linux


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
