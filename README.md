# Elevation Change

A static site. No database, no build step, no server. You edit HTML files and push them.

## Get it online (about 10 minutes, free)

1. Make a free GitHub account if you don't have one.
2. Create a new repository named `elevation-change`. Make it public.
3. Upload every file in this folder, keeping the folder structure (`articles/` and `assets/` stay as folders).
4. In the repo, go to **Settings → Pages**. Under "Build and deployment", set Source to **Deploy from a branch**, branch `main`, folder `/ (root)`. Save.
5. Wait about a minute. Your site is live at `https://yourusername.github.io/elevation-change/`.

To use your own domain later, buy one (around $12/year) and point it at GitHub Pages from the same Settings → Pages screen.

## Write your season opener

Open `articles/season-opener.html`. Everything you need to change is in the `<article>` section:

- The `<h1>` is your headline.
- The `<p class="dek">` is your subhead.
- The `<p class="byline">` has your name and the date.
- Inside `<div class="article-body">`, each `<p>...</p>` is a paragraph. Write between the tags.

Then open `index.html` and update the matching entry in the `<ul class="posts">` list so the headline and description match.

## Add a new post later

1. Copy `articles/season-opener.html` to a new file, e.g. `articles/boise-week-two.html`.
2. Replace the headline, subhead, byline, and body.
3. In `index.html`, copy one `<li>` block in the posts list, paste it above the others, and update the link, date, elevation, headline, and description.

Newest post goes at the top.

## The elevation tag

Every post carries the elevation of the venue. It's the thing that makes this site look like it has a point of view. Some to reuse:

| Venue | Elevation |
|---|---|
| War Memorial Stadium, Laramie | 7,220 ft |
| Falcon Stadium, Air Force | 6,621 ft |
| Canvas Stadium, Colorado State | 5,003 ft |
| Maverik Stadium, Utah State | 4,775 ft |
| Albertsons Stadium, Boise State | 2,730 ft |
| Reser Stadium, Oregon State | 230 ft |
| LA Memorial Coliseum | 180 ft |
| Snapdragon Stadium, San Diego State | 95 ft |

## Files

- `index.html` — home page and post list
- `articles/` — one HTML file per post
- `styles.css` — all styling; change colors at the top under `:root`
- `assets/` — logo files
