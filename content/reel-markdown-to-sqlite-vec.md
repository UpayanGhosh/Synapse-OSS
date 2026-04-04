So I was storing all my AI's memories in markdown files. Like... just plain text sitting in a folder. And it worked — until it didn't.

Here's the thing — when your AI chatbot needs to remember stuff, you need to search through those memories fast. With markdown files, every time someone sends a message, I was basically doing ctrl+F across hundreds of files. It's like trying to find a specific conversation in a year-old WhatsApp group by scrolling. It technically works, but you'll lose your mind.

And the real problem? Keyword search is dumb. If I stored a memory that says "I love biryani," and someone asks "what's my favourite food?" — keyword search finds nothing. Zero matches. Because the words are different even though the meaning is the same.

So this is where vectorisation comes in. And I promise it's simpler than it sounds.

Think of it like this. Every sentence has a vibe, right? "I love biryani" and "what's my favourite food" — different words, but the vibe is close. Vectorisation is just... converting that vibe into a list of numbers. Like GPS coordinates, but instead of latitude-longitude, you have 768 numbers that represent the meaning of a sentence.

Now when someone asks a question, I convert that into numbers too, and just find which stored memory has the closest coordinates. Instead of matching exact words, you're matching meaning. That's the magic.

So I moved everything into SQLite with an extension called sqlite-vec. One single file — memory.db — holds all my documents and their vector embeddings. No external server, no Pinecone bills, no Docker containers for a database. Just SQLite doing SQLite things.

But here's what nobody tells you in those "build RAG in 5 minutes" tutorials.

Vectors only capture vibes. That's it. They don't understand relationships.

Like, if I store "Upayan works at Acme" and "Acme is based in Bangalore" — a vector search for "where does Upayan work?" might find the first one. But it will never connect the dots that Upayan is therefore based in Bangalore. It can't do that hop. Each memory is an island.

That's why I ended up building a second database — a knowledge graph. Literally a table of subject-predicate-object triples. "Upayan works at Acme." "Acme based in Bangalore." Now you can hop across relationships.

So the real answer isn't vectors or graphs — it's both. Vectors for vibes, graphs for connections. One finds the neighbourhood, the other walks the streets.

So yeah — markdown files to sqlite-vec plus a knowledge graph. Went from 150 megs of stuff in RAM to like... 1 meg. And search actually understands what you mean now.

If you're building anything with AI memory, start with vectors, but don't stop there. Your AI needs both vibes and structure.

Link's in the bio if you wanna check the code. Peace.
