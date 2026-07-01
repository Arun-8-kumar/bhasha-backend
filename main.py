import datetime
import logging
import os
import re
import base64
import json
import random
import html
from typing import Dict, List, Optional
from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
import httpx
from dotenv import load_dotenv

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("bhasha-backend")

load_dotenv()

SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID", "")
SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET", "")

app = FastAPI(
    title="Bhasha Music API (JioSaavn-backed)",
    description="Backend API for Bhasha - using community JioSaavn API for high-fidelity audio streams.",
    version="2.0.0"
)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Gzip compression for API responses
app.add_middleware(GZipMiddleware, minimum_size=1000)

# JioSaavn API Endpoint
JIOSAAVN_API_URL = "https://saavn.sumit.co/api"

# In-memory cache for trending lists
cache: Dict[str, dict] = {}
CACHE_EXPIRY = datetime.timedelta(minutes=30)

# In-memory cache for search results
search_cache: Dict[str, dict] = {}
SEARCH_CACHE_EXPIRY = datetime.timedelta(minutes=15)

# Static High-Fidelity Fallback Data in case the API encounters errors
FALLBACK_DATA: Dict[str, List[dict]] = {
    "Telugu": [
        {
            "id": "Y_rCig5e",
            "title": "Hellallallo (From \"Peddi\")",
            "artist": "S. Thaman, Sri Krishna",
            "thumbnail": "https://c.saavncdn.com/242/Hellallallo-From-Peddi-Telugu-Telugu-2026-20260523201040-500x500.jpg",
            "audioUrl": "https://aac.saavncdn.com/242/72329de8a4203630eb2ec21518be4a7c_320.mp4",
            "album": "Peddi",
            "duration": 210
        }
    ],
    "Hindi": [
        {
            "id": "RLzC55ai0Eo",
            "title": "Heeriye (feat. Arijit Singh)",
            "artist": "Jasleen Royal, Arijit Singh, Dulquer Salmaan",
            "thumbnail": "https://c.saavncdn.com/768/Heeriye-feat-Arijit-Singh-Hindi-2023-20230725055612-500x500.jpg",
            "audioUrl": "https://aac.saavncdn.com/768/497528d087e3f71a461a72456663853e_320.mp4",
            "album": "Heeriye",
            "duration": 194
        }
    ],
    "Tamil": [
        {
            "id": "1F3hm6Mf",
            "title": "Kaavaalaa (From \"Jailer\")",
            "artist": "Anirudh Ravichander, Shilpa Rao",
            "thumbnail": "https://c.saavncdn.com/225/Jailer-Tamil-2023-20230718181005-500x500.jpg",
            "audioUrl": "https://aac.saavncdn.com/225/c9e99eb7d1620df9bfbb4740e5361fa3_320.mp4",
            "album": "Jailer",
            "duration": 182
        }
    ],
    "Bengali": [
        {
            "id": "7X2dY8g0",
            "title": "O Mon Re",
            "artist": "Shreya Ghoshal",
            "thumbnail": "https://c.saavncdn.com/765/O-Mon-Re-Bengali-2021-20211018131015-500x500.jpg",
            "audioUrl": "https://aac.saavncdn.com/765/694ab517b620e29bfe443a290dfc71e8_320.mp4",
            "album": "O Mon Re",
            "duration": 204
        }
    ],
    "English": [
        {
            "id": "4NRXx6U8",
            "title": "Blinding Lights",
            "artist": "The Weeknd",
            "thumbnail": "https://c.saavncdn.com/346/After-Hours-English-2020-500x500.jpg",
            "audioUrl": "https://aac.saavncdn.com/346/8cb45d2e3e52e443eb1bfbb47e3a11fa_320.mp4",
            "album": "After Hours",
            "duration": 200
        }
    ],
    "Spanish": [
        {
            "id": "kJQP7kiw",
            "title": "Despacito",
            "artist": "Luis Fonsi, Daddy Yankee",
            "thumbnail": "https://c.saavncdn.com/654/Despacito-Spanish-2017-500x500.jpg",
            "audioUrl": "https://aac.saavncdn.com/654/7cbdf6b7d159e19dfee2b6b0638ab1fa_320.mp4",
            "album": "Despacito",
            "duration": 228
        }
    ],
    "Telugu 90s Hits": [
        {
            "id": "Ovx9J-Gp",
            "title": "Kammani Ee Prema Lekha (From \"Guna\")",
            "artist": "S. P. Balasubrahmanyam, K. S. Chithra",
            "thumbnail": "https://c.saavncdn.com/320/Guna-Telugu-1991-500x500.jpg",
            "audioUrl": "https://aac.saavncdn.com/320/3d94eb7c1529ef8f2cbba741ea3a1fa3_320.mp4",
            "album": "Guna",
            "duration": 215
        }
    ],
    "Prabhas Hits": [
        {
            "id": "XAW915Uj",
            "title": "Saahore Baahubali",
            "artist": "M. M. Keeravani, Daler Mehndi",
            "thumbnail": "https://c.saavncdn.com/432/Baahubali-2-The-Conclusion-Telugu-2017-500x500.jpg",
            "audioUrl": "https://aac.saavncdn.com/432/7acbf6b7d165df8bfeeb47e4fa1b1fa3_320.mp4",
            "album": "Baahubali 2",
            "duration": 202
        }
    ]
}

def parse_jiosaavn_song(item: dict) -> dict:
    """
    Utility function to parse and clean a song object returned from JioSaavn API.
    Extracts the highest quality thumbnails and streaming URLs.
    """
    song_id = item.get("id")
    
    # Extract thumbnails (extract all sizes into a dictionary)
    images = item.get("image", [])
    thumbnails = {}
    thumbnail = ""
    if isinstance(images, list):
        for img in images:
            if isinstance(img, dict) and img.get("quality") and img.get("url"):
                thumbnails[img.get("quality")] = img.get("url")
        # Prefer 150x150 for list thumbnails (saves ~10x data vs 500x500)
        thumbnail = thumbnails.get("150x150", "")
        if not thumbnail:
            thumbnail = thumbnails.get("500x500", "")
        if not thumbnail and images:
            thumbnail = images[-1].get("url")
            
    # Extract audio stream link (prefer 160kbps for data savings, fallback to 96kbps, then 320kbps, then last in list)
    download_urls = item.get("downloadUrl", [])
    audio_url = ""
    if isinstance(download_urls, list):
        for dl in download_urls:
            if dl.get("quality") == "160kbps":
                audio_url = dl.get("url")
                break
        if not audio_url:
            for dl in download_urls:
                if dl.get("quality") == "96kbps":
                    audio_url = dl.get("url")
                    break
        if not audio_url:
            for dl in download_urls:
                if dl.get("quality") == "320kbps":
                    audio_url = dl.get("url")
                    break
        if not audio_url and download_urls:
            audio_url = download_urls[-1].get("url")

    # Compile a dictionary of all available stream qualities
    streams = {}
    if isinstance(download_urls, list):
        for dl in download_urls:
            if isinstance(dl, dict) and dl.get("quality") and dl.get("url"):
                q = dl.get("quality")
                u = dl.get("url")
                streams[q] = u
                if q == "48kbps":
                    streams["64kbps"] = u
                elif q == "64kbps":
                    streams["48kbps"] = u
            
    # Extract artist names from primary / all artists
    artists_list = item.get("artists", {}).get("primary", []) if isinstance(item.get("artists"), dict) else []
    if not artists_list and isinstance(item.get("artists"), dict):
        artists_list = item.get("artists", {}).get("all", [])
    
    artist_names = "Unknown Artist"
    if artists_list:
        artist_names = ", ".join([a.get("name", "") for a in artists_list if a.get("name")])
        
    album_name = "Unknown Album"
    album_data = item.get("album")
    if isinstance(album_data, dict):
        album_name = album_data.get("name", "Unknown Album")
        
    return {
        "id": song_id,
        "title": html.unescape(item.get("name", "Unknown Song")),
        "artist": html.unescape(artist_names),
        "thumbnail": thumbnail,
        "thumbnails": thumbnails,
        "audioUrl": audio_url,
        "streams": streams,
        "album": html.unescape(album_name),
        "duration": int(item.get("duration", 180) or 180)
    }

def ensure_compatibility(songs: List[dict]) -> List[dict]:
    """
    Ensures all songs in the list have compatibility properties for the frontend
    (videoId -> id, channelTitle -> artist). Also decodes HTML entities.
    """
    compat_songs = []
    for s in songs:
        copy = dict(s)
        
        # Decode HTML entities from string fields
        for field in ["title", "artist", "album", "name"]:
            if field in copy and isinstance(copy[field], str):
                copy[field] = html.unescape(copy[field])
                
        if "videoId" not in copy and "id" in copy:
            copy["videoId"] = copy["id"]
        if "channelTitle" not in copy and "artist" in copy:
            copy["channelTitle"] = copy["artist"]
            
        # Ensure channelTitle is also decoded
        if "channelTitle" in copy and isinstance(copy["channelTitle"], str):
            copy["channelTitle"] = html.unescape(copy["channelTitle"])
            
        compat_songs.append(copy)
    return compat_songs

async def fetch_jiosaavn_songs(query: str, limit: int = 10, page: int = 1) -> List[dict]:
    """
    Queries JioSaavn search/songs endpoint and returns formatted songs.
    """
    logger.info(f"Querying JioSaavn API for: '{query}' (page {page})")
    params = {
        "query": query,
        "limit": str(limit),
        "page": str(page)
    }
    
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            response = await client.get(f"{JIOSAAVN_API_URL}/search/songs", params=params)
            if response.status_code == 200:
                data = response.json()
                if data.get("success"):
                    results = data.get("data", {}).get("results", [])
                    formatted = [parse_jiosaavn_song(item) for item in results if item.get("id")]
                    logger.info(f"Successfully retrieved {len(formatted)} songs from JioSaavn")
                    return formatted
                else:
                    logger.warning(f"JioSaavn API search failed. Message: {data.get('message')}")
            else:
                logger.error(f"JioSaavn API search returned status {response.status_code}: {response.text}")
        except Exception as e:
            logger.error(f"Error fetching from JioSaavn API: {e}")
            
    # Return empty list on failure so fallbacks can be handled by endpoints
    return []

@app.get("/api/trending")
async def get_trending(languages: str = Query(..., description="Comma-separated list of languages")):
    """
    Returns trending/latest music for the selected languages, utilizing caching.
    """
    if not languages:
        raise HTTPException(status_code=400, detail="Languages parameter is required")
        
    requested_langs = [lang.strip() for lang in languages.split(",") if lang.strip()]
    
    # Expand "Telugu" to include custom sub-playlists
    final_langs = []
    for lang in requested_langs:
        final_langs.append(lang)
        if lang == "Telugu":
            if "Telugu 90s Hits" not in final_langs:
                final_langs.append("Telugu 90s Hits")
            if "Prabhas Hits" not in final_langs:
                final_langs.append("Prabhas Hits")
                
    now = datetime.datetime.now()
    results = {}
    
    for lang in final_langs:
        # Check cache
        if lang in cache:
            cache_entry = cache[lang]
            if now - cache_entry["timestamp"] < CACHE_EXPIRY:
                logger.info(f"Serving cached data for: {lang}")
                results[lang] = cache_entry["data"]
                continue
                
        # Resolve language query keywords for search
        search_query = f"{lang} latest songs"
        if lang == "Telugu 90s Hits":
            search_query = "Telugu 90s hits"
        elif lang == "Prabhas Hits":
            search_query = "Prabhas hits"
            
        songs = await fetch_jiosaavn_songs(search_query, limit=10)
        
        if songs:
            cache[lang] = {
                "timestamp": now,
                "data": songs
            }
            results[lang] = songs
        else:
            # Serve fallback list if API fails
            logger.info(f"Serving static fallback data for language: {lang}")
            fallback = FALLBACK_DATA.get(lang, FALLBACK_DATA.get("English", []))
            results[lang] = fallback
            
    return {lang: ensure_compatibility(songs_list) for lang, songs_list in results.items()}

@app.get("/api/search")
async def search_songs(
    q: str = Query(..., description="The query string to search for"),
    languages: Optional[str] = Query(None, description="Comma-separated list of preferred languages"),
    limit: int = Query(10, ge=1, le=50, description="Maximum number of search results to return")
):
    """
    Searches JioSaavn library for songs matching the query q, with language filters applied.
    Caches search results for 15 minutes to save bandwidth and API limits.
    """
    if not q or not q.strip():
        raise HTTPException(status_code=400, detail="Search query is required")

    query = q.strip()
    
    # Check search cache first
    cache_key = f"{query.lower()}:{languages.strip().lower() if languages else ''}:{limit}"
    now = datetime.datetime.now()
    if cache_key in search_cache:
        entry = search_cache[cache_key]
        if now - entry["timestamp"] < SEARCH_CACHE_EXPIRY:
            logger.info(f"Serving cached search results for: '{cache_key}'")
            return entry["data"]

    logger.info(f"Search request for: '{query}' with preferred languages: '{languages}' and limit: {limit}")

    # If preferred languages are specified, refine the query to yield better results
    refined_query = query
    if languages:
        requested_langs = [lang.strip() for lang in languages.split(",") if lang.strip()]
        if requested_langs:
            query_lower = query.lower()
            if not any(l.lower() in query_lower for l in requested_langs):
                # Append languages to the search query to bias the search
                lang_filter = " ".join(requested_langs)
                refined_query = f"{query} {lang_filter}"
                logger.info(f"Refined search query: '{refined_query}'")

    songs = await fetch_jiosaavn_songs(refined_query, limit=limit)
    
    if not songs:
        # Return fallback search results from static list
        logger.info(f"Applying robust fallback search for query: '{q}'")
        query_lower = q.lower().strip()
        matches = []
        for lang, song_list in FALLBACK_DATA.items():
            for song in song_list:
                if query_lower in song["title"].lower() or query_lower in song["artist"].lower():
                    matches.append(song)
        if matches:
            compat_songs = ensure_compatibility(matches[:limit])
        else:
            # Global ultimate fallback
            compat_songs = ensure_compatibility(FALLBACK_DATA.get("English", []))
    else:
        compat_songs = ensure_compatibility(songs)
        
    # Store in search cache
    search_cache[cache_key] = {
        "timestamp": now,
        "data": compat_songs
    }
    
    return compat_songs

# ==========================================
# Mood Mix API Feature
# ==========================================

MOOD_QUERIES = {
    "Energetic": "dance",
    "Chill": "relax",
    "Romantic": "romantic",
    "Happy": "upbeat",
    "Sad": "sad",
    "Focus": "instrumental"
}

def get_mood_search_term(mood: str, language: str) -> str:
    lang_lower = language.lower()
    is_regional = lang_lower in ["telugu", "hindi", "tamil", "bengali", "telugu 90s hits", "prabhas hits"]
    
    if mood == "Energetic":
        return "mass" if lang_lower in ["telugu", "tamil", "prabhas hits"] else "dance"
    elif mood == "Chill":
        return "melody" if is_regional else "relax"
    elif mood == "Romantic":
        return "romantic"
    elif mood == "Happy":
        return "upbeat"
    elif mood == "Sad":
        return "sad"
    elif mood == "Focus":
        return "instrumental"
    return "music"

# User-added songs by Mood
USER_CUSTOM_MOOD_DATA: Dict[str, List[dict]] = {
    "Energetic": [
      {
        "id": "sewkau4E",
        "title": "Single's Anthem",
        "artist": "Anurag Kulkarni",
        "thumbnail": "https://c.saavncdn.com/558/Bheeshma-Telugu-2019-20200320104145-500x500.jpg",
        "audioUrl": "https://aac.saavncdn.com/558/117d6761ead206696a3d38021db32d00_320.mp4",
        "album": "Bheeshma",
        "duration": 203
      },
      {
        "id": "KGsieyqf",
        "title": "Jarra Jarra",
        "artist": "Mickey J. Meyer, Anurag Kulkarni, Uma Neha, Bhaskarbhatla Ravikumar",
        "thumbnail": "https://c.saavncdn.com/305/Valmiki-Telugu-2019-20190912124556-500x500.jpg",
        "audioUrl": "https://aac.saavncdn.com/305/24ce3429d8e69d10a75890d64f6c1e5e_320.mp4",
        "album": "Valmiki",
        "duration": 181
      },
      {
        "id": "5i2jEmfq",
        "title": "Rakita Rakita Rakita",
        "artist": "Dhanush, Santhosh Narayanan, Dhee, Vivek",
        "thumbnail": "https://c.saavncdn.com/384/Namma-Pongal-Vibes-2026-Tamil-2026-20260107173615-500x500.jpg",
        "audioUrl": "https://aac.saavncdn.com/384/a23b2320e1d6c68722c0cd45618b11e7_320.mp4",
        "album": "Namma Pongal Vibes 2026",
        "duration": 247
      },
      {
        "id": "WrGU-iqE",
        "title": "Ramuloo Ramulaa",
        "artist": "Anurag Kulkarni, Mangli",
        "thumbnail": "https://c.saavncdn.com/517/Ala-Vaikunthapurramuloo-Telugu-2019-20200116144338-500x500.jpg",
        "audioUrl": "https://aac.saavncdn.com/517/5702757c42c1ad44b3224a339817c8b0_320.mp4",
        "album": "Ala Vaikunthapurramuloo",
        "duration": 245
      },
      {
        "id": "PCYT5rDb",
        "title": "Bujji",
        "artist": "Santhosh Narayanan, Anirudh Ravichander, Vivek",
        "thumbnail": "https://c.saavncdn.com/212/Jagame-Thandhiram-Original-Motion-Picture-Soundtrack--Tamil-2021-20210607095427-500x500.jpg",
        "audioUrl": "https://aac.saavncdn.com/212/c2300b1e53abc0867387c85afb4d4c61_320.mp4",
        "album": "Jagame Thandhiram",
        "duration": 267
      },
      {
        "id": "eDfbxp3y",
        "title": "Psycho Saiyaan",
        "artist": "Anirudh Ravichander, Dhvani Bhanushali, Tanishk Bagchi",
        "thumbnail": "https://c.saavncdn.com/186/Saaho-Telugu-2019-20190828024553-500x500.jpg",
        "audioUrl": "https://aac.saavncdn.com/186/a222291941fa50e393e794a3f25b174e_320.mp4",
        "album": "Saaho",
        "duration": 166
      },
      {
        "id": "tfX08D09",
        "title": "Rowdy Baby (From \"Maari 2\")",
        "artist": "Dhanush, Dhee",
        "thumbnail": "https://c.saavncdn.com/704/The-Prodigious-Dhanush-Tamil-2020-20200724184227-500x500.jpg",
        "audioUrl": "https://aac.saavncdn.com/704/93fc2fb3cc2eb3033e91e5fa0af5ef81_320.mp4",
        "album": "The Prodigious Dhanush",
        "duration": 281
      },
      {
        "id": "LYLac8S7",
        "title": "Bad Boy",
        "artist": "Badshah, Neeti Mohan",
        "thumbnail": "https://c.saavncdn.com/186/Saaho-Telugu-2019-20190828024553-500x500.jpg",
        "audioUrl": "https://aac.saavncdn.com/186/d58880cd3609c1de2695cb11b4eae664_320.mp4",
        "album": "Saaho",
        "duration": 177
      },
      {
        "id": "jYhoRWbC",
        "title": "Massu Maranam (From \"Petta (Telugu)\")",
        "artist": "Anirudh Ravichander, Mano",
        "thumbnail": "https://c.saavncdn.com/699/Petta-Telugu--Telugu-2018-20181220071359-500x500.jpg",
        "audioUrl": "https://aac.saavncdn.com/699/e80638202684ecce1ac1c2b2168ab442_320.mp4",
        "album": "Petta (Telugu)",
        "duration": 216
      },
      {
        "id": "SNQKClWW",
        "title": "Single Kingulam",
        "artist": "Hiphop Tamizha, Rahul Sipligunj",
        "thumbnail": "https://c.saavncdn.com/851/A1-Express-Original-Motion-Picture-Soundtrack-Telugu-2021-20251024161308-500x500.jpg",
        "audioUrl": "https://aac.saavncdn.com/851/d9141a685d59f62f0eaac82442a8acfa_320.mp4",
        "album": "A1 Express (Original Motion Picture Soundtrack)",
        "duration": 224
      },
      {
        "id": "JizCVRX6",
        "title": "Ra Ra (Roar of the Revengers)",
        "artist": "Anirudh Ravichander, Prudhvi Chandra, Bashermax",
        "thumbnail": "https://c.saavncdn.com/663/Gang-Leader-Telugu-2019-20190905102749-500x500.jpg",
        "audioUrl": "https://aac.saavncdn.com/663/29ff7886ad7b08e6d3ef3044366c3520_320.mp4",
        "album": "Gang Leader",
        "duration": 250
      },
      {
        "id": "GiT1_-LG",
        "title": "Dhruva Dhruva (From \"Dhruva\")",
        "artist": "Amit Mishra",
        "thumbnail": "https://c.saavncdn.com/000/Mega-Power-Star-Ram-Charan-Hits-Telugu-2022-20220323194638-500x500.jpg",
        "audioUrl": "https://aac.saavncdn.com/000/b0a2fa0f8edbe7ffb2d8b804a5b68d13_320.mp4",
        "album": "Mega Power Star Ram Charan Hits",
        "duration": 207
      },
      {
        "id": "dG7VkQKS",
        "title": "Raavana",
        "artist": "Divya Kumar",
        "thumbnail": "https://c.saavncdn.com/430/Jai-Lava-Kusa-Telugu-2017-20250814181609-500x500.jpg",
        "audioUrl": "https://aac.saavncdn.com/430/b029771c9c69ad25f6a338ba1e01109a_320.mp4",
        "album": "Jai Lava Kusa",
        "duration": 258
      },
      {
        "id": "AgeRwxTb",
        "title": "Arabic Kuthu - Halamithi Habibo",
        "artist": "Anirudh Ravichander, Jonita Gandhi",
        "thumbnail": "https://c.saavncdn.com/510/Beast-Tamil-2022-20220504184736-500x500.jpg",
        "audioUrl": "https://aac.saavncdn.com/510/9d96fc7ddd4ffadb745f25aed86f7a4e_320.mp4",
        "album": "Beast",
        "duration": 279
      },
      {
        "id": "5OjdY4fM",
        "title": "Tillu Anna DJ Pedithe",
        "artist": "Ram Miriyala",
        "thumbnail": "https://c.saavncdn.com/430/DJ-Tillu-Telugu-2022-20220210033850-500x500.jpg",
        "audioUrl": "https://aac.saavncdn.com/430/7c1e7a6ca761e7db04d9169208d46eca_320.mp4",
        "album": "DJ Tillu",
        "duration": 183
      },
      {
        "id": "EwWjEcGi",
        "title": "Jalabulajangu",
        "artist": "Anirudh Ravichander, Rokesh",
        "thumbnail": "https://c.saavncdn.com/435/Don-Tamil-2022-20220512162818-500x500.jpg",
        "audioUrl": "https://aac.saavncdn.com/435/8978e3a1d9c992345afce463e496db42_320.mp4",
        "album": "Don",
        "duration": 202
      },
      {
        "id": "HrKxFXg8",
        "title": "Naan Naan",
        "artist": "Vivek, Santhosh Narayanan",
        "thumbnail": "https://c.saavncdn.com/362/Mahaan-Tamil-2022-20260608143837-500x500.jpg",
        "audioUrl": "https://aac.saavncdn.com/362/d0c8dc0173916f5a1f0e1e720e149193_320.mp4",
        "album": "Mahaan",
        "duration": 248
      },
      {
        "id": "DSIIXJ3U",
        "title": "FRIENDS (Originally Perfomed By Marshmello, Anne-Marie) (Instrumental Karaoke Version)",
        "artist": "ZZang KARAOKE",
        "thumbnail": "https://c.saavncdn.com/529/ZZang-KARAOKE-Greatest-POP-Vol-7-Instrumental-2024-20260120110416-500x500.jpg",
        "audioUrl": "https://aac.saavncdn.com/529/9d7716cecc036036ac4cdeda22392599_320.mp4",
        "album": "ZZang KARAOKE Greatest POP Vol.7",
        "duration": 209
      }
    ],
    "Sad": [],
    "Romantic": [],
    "Happy": [],
    "Chill": [],
    "Focus": []
}

# Static fallback songs by Mood in case the JioSaavn API is offline
FALLBACK_MOOD_DATA: Dict[str, List[dict]] = {
    "Energetic": [
        {
            "id": "Y_rCig5e",
            "title": "Hellallallo (From \"Peddi\")",
            "artist": "S. Thaman, Sri Krishna",
            "thumbnail": "https://c.saavncdn.com/242/Hellallallo-From-Peddi-Telugu-Telugu-2026-20260523201040-500x500.jpg",
            "audioUrl": "https://aac.saavncdn.com/242/72329de8a4203630eb2ec21518be4a7c_320.mp4",
            "album": "Peddi",
            "duration": 210
        },
        {
            "id": "1F3hm6Mf",
            "title": "Kaavaalaa (From \"Jailer\")",
            "artist": "Anirudh Ravichander, Shilpa Rao",
            "thumbnail": "https://c.saavncdn.com/225/Jailer-Tamil-2023-20230718181005-500x500.jpg",
            "audioUrl": "https://aac.saavncdn.com/225/c9e99eb7d1620df9bfbb4740e5361fa3_320.mp4",
            "album": "Jailer",
            "duration": 182
        },
        {
            "id": "kJQP7kiw",
            "title": "Despacito",
            "artist": "Luis Fonsi, Daddy Yankee",
            "thumbnail": "https://c.saavncdn.com/654/Despacito-Spanish-2017-500x500.jpg",
            "audioUrl": "https://aac.saavncdn.com/654/7cbdf6b7d159e19dfee2b6b0638ab1fa_320.mp4",
            "album": "Despacito",
            "duration": 228
        },
        {
            "id": "XAW915Uj",
            "title": "Saahore Baahubali",
            "artist": "M. M. Keeravani, Daler Mehndi",
            "thumbnail": "https://c.saavncdn.com/432/Baahubali-2-The-Conclusion-Telugu-2017-500x500.jpg",
            "audioUrl": "https://aac.saavncdn.com/432/7acbf6b7d165df8bfeeb47e4fa1b1fa3_320.mp4",
            "album": "Baahubali 2",
            "duration": 202
        }
    ],
    "Chill": [
        {
            "id": "RLzC55ai0Eo",
            "title": "Heeriye (feat. Arijit Singh)",
            "artist": "Jasleen Royal, Arijit Singh, Dulquer Salmaan",
            "thumbnail": "https://c.saavncdn.com/768/Heeriye-feat-Arijit-Singh-Hindi-2023-20230725055612-500x500.jpg",
            "audioUrl": "https://aac.saavncdn.com/768/497528d087e3f71a461a72456663853e_320.mp4",
            "album": "Heeriye",
            "duration": 194
        },
        {
            "id": "7X2dY8g0",
            "title": "O Mon Re",
            "artist": "Shreya Ghoshal",
            "thumbnail": "https://c.saavncdn.com/765/O-Mon-Re-Bengali-2021-20211018131015-500x500.jpg",
            "audioUrl": "https://aac.saavncdn.com/765/694ab517b620e29bfe443a290dfc71e8_320.mp4",
            "album": "O Mon Re",
            "duration": 204
        },
        {
            "id": "Ovx9J-Gp",
            "title": "Kammani Ee Prema Lekha (From \"Guna\")",
            "artist": "S. P. Balasubrahmanyam, K. S. Chithra",
            "thumbnail": "https://c.saavncdn.com/320/Guna-Telugu-1991-500x500.jpg",
            "audioUrl": "https://aac.saavncdn.com/320/3d94eb7c1529ef8f2cbba741ea3a1fa3_320.mp4",
            "album": "Guna",
            "duration": 215
        }
    ],
    "Romantic": [
        {
            "id": "RLzC55ai0Eo",
            "title": "Heeriye (feat. Arijit Singh)",
            "artist": "Jasleen Royal, Arijit Singh, Dulquer Salmaan",
            "thumbnail": "https://c.saavncdn.com/768/Heeriye-feat-Arijit-Singh-Hindi-2023-20230725055612-500x500.jpg",
            "audioUrl": "https://aac.saavncdn.com/768/497528d087e3f71a461a72456663853e_320.mp4",
            "album": "Heeriye",
            "duration": 194
        },
        {
            "id": "7X2dY8g0",
            "title": "O Mon Re",
            "artist": "Shreya Ghoshal",
            "thumbnail": "https://c.saavncdn.com/765/O-Mon-Re-Bengali-2021-20211018131015-500x500.jpg",
            "audioUrl": "https://aac.saavncdn.com/765/694ab517b620e29bfe443a290dfc71e8_320.mp4",
            "album": "O Mon Re",
            "duration": 204
        },
        {
            "id": "Ovx9J-Gp",
            "title": "Kammani Ee Prema Lekha (From \"Guna\")",
            "artist": "S. P. Balasubrahmanyam, K. S. Chithra",
            "thumbnail": "https://c.saavncdn.com/320/Guna-Telugu-1991-500x500.jpg",
            "audioUrl": "https://aac.saavncdn.com/320/3d94eb7c1529ef8f2cbba741ea3a1fa3_320.mp4",
            "album": "Guna",
            "duration": 215
        }
    ],
    "Happy": [
        {
            "id": "4NRXx6U8",
            "title": "Blinding Lights",
            "artist": "The Weeknd",
            "thumbnail": "https://c.saavncdn.com/346/After-Hours-English-2020-500x500.jpg",
            "audioUrl": "https://aac.saavncdn.com/346/8cb45d2e3e52e443eb1bfbb47e3a11fa_320.mp4",
            "album": "After Hours",
            "duration": 200
        },
        {
            "id": "Y_rCig5e",
            "title": "Hellallallo (From \"Peddi\")",
            "artist": "S. Thaman, Sri Krishna",
            "thumbnail": "https://c.saavncdn.com/242/Hellallallo-From-Peddi-Telugu-Telugu-2026-20260523201040-500x500.jpg",
            "audioUrl": "https://aac.saavncdn.com/242/72329de8a4203630eb2ec21518be4a7c_320.mp4",
            "album": "Peddi",
            "duration": 210
        },
        {
            "id": "1F3hm6Mf",
            "title": "Kaavaalaa (From \"Jailer\")",
            "artist": "Anirudh Ravichander, Shilpa Rao",
            "thumbnail": "https://c.saavncdn.com/225/Jailer-Tamil-2023-20230718181005-500x500.jpg",
            "audioUrl": "https://aac.saavncdn.com/225/c9e99eb7d1620df9bfbb4740e5361fa3_320.mp4",
            "album": "Jailer",
            "duration": 182
        }
    ],
    "Sad": [
        {
            "id": "RLzC55ai0Eo",
            "title": "Heeriye (feat. Arijit Singh)",
            "artist": "Jasleen Royal, Arijit Singh, Dulquer Salmaan",
            "thumbnail": "https://c.saavncdn.com/768/Heeriye-feat-Arijit-Singh-Hindi-2023-20230725055612-500x500.jpg",
            "audioUrl": "https://aac.saavncdn.com/768/497528d087e3f71a461a72456663853e_320.mp4",
            "album": "Heeriye",
            "duration": 194
        },
        {
            "id": "7X2dY8g0",
            "title": "O Mon Re",
            "artist": "Shreya Ghoshal",
            "thumbnail": "https://c.saavncdn.com/765/O-Mon-Re-Bengali-2021-20211018131015-500x500.jpg",
            "audioUrl": "https://aac.saavncdn.com/765/694ab517b620e29bfe443a290dfc71e8_320.mp4",
            "album": "O Mon Re",
            "duration": 204
        },
        {
            "id": "Ovx9J-Gp",
            "title": "Kammani Ee Prema Lekha (From \"Guna\")",
            "artist": "S. P. Balasubrahmanyam, K. S. Chithra",
            "thumbnail": "https://c.saavncdn.com/320/Guna-Telugu-1991-500x500.jpg",
            "audioUrl": "https://aac.saavncdn.com/320/3d94eb7c1529ef8f2cbba741ea3a1fa3_320.mp4",
            "album": "Guna",
            "duration": 215
        }
    ],
    "Focus": [
        {
            "id": "Ovx9J-Gp",
            "title": "Kammani Ee Prema Lekha (From \"Guna\")",
            "artist": "S. P. Balasubrahmanyam, K. S. Chithra",
            "thumbnail": "https://c.saavncdn.com/320/Guna-Telugu-1991-500x500.jpg",
            "audioUrl": "https://aac.saavncdn.com/320/3d94eb7c1529ef8f2cbba741ea3a1fa3_320.mp4",
            "album": "Guna",
            "duration": 215
        },
        {
            "id": "XAW915Uj",
            "title": "Saahore Baahubali",
            "artist": "M. M. Keeravani, Daler Mehndi",
            "thumbnail": "https://c.saavncdn.com/432/Baahubali-2-The-Conclusion-Telugu-2017-500x500.jpg",
            "audioUrl": "https://aac.saavncdn.com/432/7acbf6b7d165df8bfeeb47e4fa1b1fa3_320.mp4",
            "album": "Baahubali 2",
            "duration": 202
        }
    ]
}

@app.get("/api/songs/mood")
async def get_mood_songs(
    mood: str = Query(..., description="The mood of songs to fetch"),
    languages: Optional[str] = Query(None, description="Comma-separated preferred languages"),
    page: int = Query(1, description="Page number for pagination")
):
    """
    Returns a list of songs matching a specific mood and preferred languages.
    """
    mood_key = mood.strip()
    if mood_key not in MOOD_QUERIES:
        raise HTTPException(status_code=400, detail=f"Invalid mood. Choose from: {list(MOOD_QUERIES.keys())}")
        
    songs = []
    
    # Prepend custom user songs for the specific mood (only on page 1)
    if page == 1:
        custom_songs = USER_CUSTOM_MOOD_DATA.get(mood_key, [])
        songs.extend(custom_songs)
    
    # 1. Fetch language-specific mood songs
    if languages:
        requested_langs = [lang.strip() for lang in languages.split(",") if lang.strip()]
        for lang in requested_langs:
            term = get_mood_search_term(mood_key, lang)
            search_query = f"{lang} {term}"
            lang_songs = await fetch_jiosaavn_songs(search_query, limit=15, page=page)
            songs.extend(lang_songs)
            
    # 2. Fill up with generic mood search if we don't have enough songs
    if len(songs) < 10:
        query_base = MOOD_QUERIES[mood_key]
        generic_songs = await fetch_jiosaavn_songs(query_base, limit=15, page=page)
        existing_ids = {s["id"] for s in songs}
        for s in generic_songs:
            if s["id"] not in existing_ids:
                songs.append(s)
                if len(songs) >= 20:
                    break
                    
    # 3. Fallback to static fallback data if API completely fails or returns too few results
    if len(songs) < 3:
        logger.info(f"Serving static fallback data for mood: {mood_key}")
        fallback_list = list(FALLBACK_MOOD_DATA.get(mood_key, []))
        
        # Sort fallback list so that songs matching preferred languages come first
        if languages:
            requested_langs = [l.lower() for l in languages.split(",") if l.strip()]
            
            def language_priority(song):
                title = song["title"].lower()
                artist = song["artist"].lower()
                album = song.get("album", "").lower()
                for l in requested_langs:
                    if l == "telugu" and ("guna" in album or "peddi" in album or "baahubali" in album or "thaman" in artist or "balasubrahmanyam" in artist or "keeravani" in artist):
                        return 0
                    if l == "tamil" and ("jailer" in album or "anirudh" in artist):
                        return 0
                    if l == "hindi" and ("arijit" in artist or "jasleen" in artist):
                        return 0
                    if l == "bengali" and ("ghoshal" in artist or "mon re" in title):
                        return 0
                    if l == "spanish" and ("despacito" in title or "fonsi" in artist):
                        return 0
                    if l == "english" and ("weeknd" in artist or "blinding" in title):
                        return 0
                return 1
                
            fallback_list.sort(key=language_priority)
        songs = fallback_list
        
    # Filter duplicates
    seen_ids = set()
    unique_songs = []
    for s in songs:
        if s["id"] not in seen_ids:
            seen_ids.add(s["id"])
            unique_songs.append(s)
    songs = unique_songs

    return ensure_compatibility(songs)

# ==========================================
# Spotify Playlist Import Feature API
# ==========================================

def extract_playlist_id(url: str) -> Optional[str]:
    match = re.search(r"playlist[/:]([a-zA-Z0-9]+)", url)
    return match.group(1) if match else None

async def get_spotify_token(client_id: str, client_secret: str) -> str:
    auth_str = f"{client_id}:{client_secret}"
    auth_b64 = base64.b64encode(auth_str.encode()).decode()
    headers = {
        "Authorization": f"Basic {auth_b64}",
        "Content-Type": "application/x-www-form-urlencoded"
    }
    data = {
        "grant_type": "client_credentials"
    }
    async with httpx.AsyncClient() as client:
        response = await client.post("https://accounts.spotify.com/api/token", headers=headers, data=data)
        if response.status_code == 200:
            return response.json().get("access_token")
        else:
            raise Exception(f"Spotify authentication failed (HTTP {response.status_code}): {response.text}")

async def get_spotify_playlist_meta(playlist_id: str, token: str) -> dict:
    headers = {
        "Authorization": f"Bearer {token}"
    }
    url = f"https://api.spotify.com/v1/playlists/{playlist_id}"
    async with httpx.AsyncClient() as client:
        response = await client.get(url, headers=headers)
        if response.status_code == 200:
            data = response.json()
            images = data.get("images", [])
            thumbnail = images[0].get("url") if images else ""
            return {
                "name": data.get("name", "Imported Playlist"),
                "description": data.get("description", "A custom imported Spotify Playlist"),
                "thumbnail": thumbnail
            }
        else:
            raise Exception(f"Failed to fetch Spotify playlist metadata: {response.text}")

async def get_spotify_tracks(playlist_id: str, token: str) -> List[dict]:
    headers = {
        "Authorization": f"Bearer {token}"
    }
    url = f"https://api.spotify.com/v1/playlists/{playlist_id}/tracks?limit=100"
    tracks = []
    async with httpx.AsyncClient() as client:
        while url and len(tracks) < 500:
            response = await client.get(url, headers=headers)
            if response.status_code == 200:
                data = response.json()
                items = data.get("items", [])
                for item in items:
                    track = item.get("track")
                    if not track:
                        continue
                    name = track.get("name")
                    artists = [a.get("name") for a in track.get("artists", [])]
                    artist_str = ", ".join(artists) if artists else "Unknown Artist"
                    tracks.append({
                        "name": name,
                        "artist": artist_str
                    })
                url = data.get("next")
            else:
                raise Exception(f"Failed to fetch Spotify tracks: {response.text}")
        return tracks

async def scrape_spotify_playlist_fallback(playlist_id: str) -> dict:
    url = f"https://open.spotify.com/embed/playlist/{playlist_id}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(url, headers=headers)
        if response.status_code != 200:
            raise Exception(f"Failed to scrape Spotify embed page (HTTP {response.status_code})")
        
        match = re.search(r'<script[^>]*type="application/json"[^>]*>({.*?})</script>', response.text)
        if not match:
            raise Exception("Failed to locate JSON state in Spotify embed page HTML")
            
        js = json.loads(match.group(1))
        props = js.get("props", {})
        page_props = props.get("pageProps", {})
        state = page_props.get("state", {})
        data = state.get("data", {})
        entity = data.get("entity", {})
        
        title = entity.get("title", "Imported Spotify Playlist")
        subtitle = entity.get("subtitle", "A custom imported Spotify Playlist")
        cover_art_sources = entity.get("coverArt", {}).get("sources", [])
        thumbnail = cover_art_sources[0].get("url", "") if cover_art_sources else ""
        
        tracks = []
        track_list = entity.get("trackList", [])
        for item in track_list:
            name = item.get("title", "Unknown Track")
            artist = item.get("subtitle", "Unknown Artist")
            tracks.append({
                "name": name,
                "artist": artist
            })
            
        return {
            "name": title,
            "description": subtitle,
            "thumbnail": thumbnail,
            "tracks": tracks
        }

async def search_youtube_track(song_name: str, artist: str) -> Optional[str]:
    """
    Searches YouTube for a fallback video ID if JioSaavn API fails.
    """
    api_key = os.getenv("YOUTUBE_API_KEY", "")
    if not api_key:
        logger.warning("YouTube API key is missing. Skipping YouTube fallback search.")
        return None
        
    query = f"{song_name} {artist}"
    logger.info(f"Resolving track on YouTube API fallback: '{query}'")
    url = "https://www.googleapis.com/youtube/v3/search"
    params = {
        "part": "snippet",
        "q": query,
        "key": api_key,
        "type": "video",
        "maxResults": "1"
    }
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            response = await client.get(url, params=params)
            if response.status_code == 200:
                data = response.json()
                items = data.get("items", [])
                if items:
                    video_id = items[0].get("id", {}).get("videoId")
                    if video_id:
                        logger.info(f"Found YouTube fallback video: {video_id} for '{query}'")
                        return video_id
            else:
                logger.error(f"YouTube API returned status {response.status_code}: {response.text}")
        except Exception as e:
            logger.error(f"Error querying YouTube API: {e}")
    return None

async def resolve_jiosaavn_track(song_name: str, artist: str) -> dict:
    """
    Resolves a Spotify track by searching JioSaavn, with a YouTube API fallback.
    """
    search_query = f"{song_name} {artist}"
    logger.info(f"Resolving track on JioSaavn: '{search_query}'")
    
    songs = await fetch_jiosaavn_songs(search_query, limit=1)
    if songs:
        return songs[0]
        
    # Fallback search on song title only
    songs = await fetch_jiosaavn_songs(song_name, limit=1)
    if songs:
        return songs[0]
        
    # Try YouTube fallback search
    yt_video_id = await search_youtube_track(song_name, artist)
    if yt_video_id:
        return {
            "id": yt_video_id,
            "title": song_name,
            "artist": artist,
            "thumbnail": f"https://img.youtube.com/vi/{yt_video_id}/hqdefault.jpg",
            "audioUrl": "",
            "album": "YouTube Audio Fallback",
            "duration": 180
        }
        
    # Final dummy object if not found anywhere
    return {
        "id": f"dummy_{hash(song_name)}",
        "title": song_name,
        "artist": artist,
        "thumbnail": "https://images.unsplash.com/photo-1614613535308-eb5fbd3d2c17?w=500&q=80",
        "audioUrl": "",
        "album": "Imported Single",
        "duration": 180
    }

@app.get("/api/spotify/import")
async def import_spotify_playlist(
    url: str = Query(..., description="The Spotify playlist URL"),
    client_id: Optional[str] = Query(None, description="Spotify Client ID"),
    client_secret: Optional[str] = Query(None, description="Spotify Client Secret")
):
    """
    Imports a Spotify playlist, parses the tracks, and resolves them to direct JioSaavn streaming links.
    """
    cid = client_id or SPOTIFY_CLIENT_ID
    csec = client_secret or SPOTIFY_CLIENT_SECRET
    
    playlist_id = extract_playlist_id(url)
    if not playlist_id:
        raise HTTPException(status_code=400, detail="Invalid Spotify playlist URL.")
        
    meta = None
    spotify_tracks = None
    
    try:
        logger.info(f"Importing playlist {playlist_id}...")
        token = await get_spotify_token(cid, csec)
        meta = await get_spotify_playlist_meta(playlist_id, token)
        spotify_tracks = await get_spotify_tracks(playlist_id, token)
    except Exception as api_err:
        logger.warning(f"Spotify API failed ({api_err}). Running scraping fallback...")
        try:
            fallback_data = await scrape_spotify_playlist_fallback(playlist_id)
            meta = {
                "name": fallback_data["name"],
                "description": fallback_data["description"],
                "thumbnail": fallback_data["thumbnail"]
            }
            spotify_tracks = fallback_data["tracks"]
        except Exception as scrape_err:
            raise HTTPException(
                status_code=400,
                detail=f"Import failed. API: {api_err}. Scraper: {scrape_err}"
            )
            
    try:
        # Increase the limit to 500 tracks
        spotify_tracks = spotify_tracks[:500]
        
        # Concurrently resolve tracks on JioSaavn with a semaphore to prevent timeouts
        import asyncio
        sem = asyncio.Semaphore(15)
        
        async def resolve_with_sem(t):
            async with sem:
                try:
                    return await resolve_jiosaavn_track(t["name"], t["artist"])
                except Exception as e:
                    logger.error(f"Error resolving track {t.get('name')}: {e}")
                    return {
                        "id": f"dummy_{hash(t.get('name', ''))}",
                        "title": t.get("name", "Unknown Track"),
                        "artist": t.get("artist", "Unknown Artist"),
                        "thumbnail": "https://images.unsplash.com/photo-1614613535308-eb5fbd3d2c17?w=500&q=80",
                        "audioUrl": "",
                        "album": "Imported Single",
                        "duration": 180
                    }
                    
        tasks = [resolve_with_sem(track) for track in spotify_tracks]
        resolved_tracks = await asyncio.gather(*tasks)
            
        logger.info(f"Import successful! '{meta['name']}' has {len(resolved_tracks)} tracks.")
        return {
            "name": meta["name"],
            "description": meta["description"],
            "thumbnail": meta["thumbnail"],
            "tracks": ensure_compatibility(resolved_tracks)
        }
    except Exception as e:
        logger.error(f"Error during track resolution: {e}")
        raise HTTPException(status_code=400, detail=f"Error resolving tracks: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
