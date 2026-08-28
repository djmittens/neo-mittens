package main

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"strconv"
	"time"

	bolt "go.etcd.io/bbolt"
)

var (
	bucketArticles = []byte("articles")
	bucketSeen     = []byte("seen") // url -> first-seen unixnano (for /htmlfeed dating)
)

type cachedArticle struct {
	HTML  string `json:"html"`
	Title string `json:"title"`
	TS    int64  `json:"ts"`
}

func openCache(path string) (*bolt.DB, error) {
	db, err := bolt.Open(path, 0o600, &bolt.Options{Timeout: 5 * time.Second})
	if err != nil {
		return nil, err
	}
	err = db.Update(func(tx *bolt.Tx) error {
		if _, e := tx.CreateBucketIfNotExists(bucketArticles); e != nil {
			return e
		}
		_, e := tx.CreateBucketIfNotExists(bucketSeen)
		return e
	})
	if err != nil {
		db.Close()
		return nil, err
	}
	return db, nil
}

// firstSeen returns the stored first-seen time for a URL, or records and returns
// candidate if this is the first time we've seen it. Used to date /htmlfeed items
// (which have no real publication dates) stably, so new entries surface as new.
func firstSeen(db *bolt.DB, url string, candidate time.Time) time.Time {
	result := candidate
	_ = db.Update(func(tx *bolt.Tx) error {
		b := tx.Bucket(bucketSeen)
		if v := b.Get(cacheKey(url)); v != nil {
			if n, err := strconv.ParseInt(string(v), 10, 64); err == nil {
				result = time.Unix(0, n)
				return nil
			}
		}
		return b.Put(cacheKey(url), []byte(strconv.FormatInt(candidate.UnixNano(), 10)))
	})
	return result
}

func cacheKey(s string) []byte {
	h := sha256.Sum256([]byte(s))
	return []byte(hex.EncodeToString(h[:]))
}

func getArticle(db *bolt.DB, url string, ttl time.Duration) (*cachedArticle, bool) {
	var out *cachedArticle
	_ = db.View(func(tx *bolt.Tx) error {
		v := tx.Bucket(bucketArticles).Get(cacheKey(url))
		if v == nil {
			return nil
		}
		var c cachedArticle
		if json.Unmarshal(v, &c) != nil {
			return nil
		}
		if ttl <= 0 || time.Since(time.Unix(c.TS, 0)) < ttl {
			out = &c
		}
		return nil
	})
	return out, out != nil
}

func putArticle(db *bolt.DB, url string, c *cachedArticle) {
	c.TS = time.Now().Unix()
	_ = db.Update(func(tx *bolt.Tx) error {
		v, err := json.Marshal(c)
		if err != nil {
			return err
		}
		return tx.Bucket(bucketArticles).Put(cacheKey(url), v)
	})
}
