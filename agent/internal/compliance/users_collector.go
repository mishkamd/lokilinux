package compliance

import (
	"bufio"
	"context"
	"io"
	"os"
	"strconv"
	"strings"
	"time"
)

// UsersCollector reports local OS accounts with UID >= 1000 and a real
// login shell — the same filter agent/internal/modules/system_info.go's
// systemUsers() already applies (service/system accounts and nologin/false
// shells excluded), but returning full user records (uid, gid, home, shell)
// rather than just names, since compliance rules need to check e.g. shell
// or home directory, not just presence.
type UsersCollector struct{}

func NewUsersCollector() *UsersCollector { return &UsersCollector{} }

func (c *UsersCollector) Domain() string { return "users" }

func (c *UsersCollector) Interval() time.Duration { return 0 }

func (c *UsersCollector) Collect(ctx context.Context) (Facts, error) {
	f, err := os.Open("/etc/passwd")
	if err != nil {
		return nil, err
	}
	defer f.Close()

	return Facts{"users": parsePasswdFile(f)}, nil
}

// User is one parsed /etc/passwd entry that passed the UID/shell filter.
type User struct {
	Name  string `json:"name"`
	UID   int    `json:"uid"`
	GID   int    `json:"gid"`
	Home  string `json:"home"`
	Shell string `json:"shell"`
}

// parsePasswdFile takes an io.Reader (not a hardcoded path) so it's
// testable with a strings.Reader instead of a real /etc/passwd.
func parsePasswdFile(r io.Reader) []User {
	var users []User
	scanner := bufio.NewScanner(r)
	for scanner.Scan() {
		fields := strings.Split(scanner.Text(), ":")
		if len(fields) < 7 {
			continue
		}
		uid, err := strconv.Atoi(fields[2])
		if err != nil || uid < 1000 {
			continue
		}
		shell := fields[6]
		if strings.HasSuffix(shell, "nologin") || strings.HasSuffix(shell, "/false") {
			continue
		}
		gid, _ := strconv.Atoi(fields[3]) // malformed GID degrades to 0 rather than dropping the whole user
		users = append(users, User{
			Name: fields[0], UID: uid, GID: gid, Home: fields[5], Shell: shell,
		})
	}
	return users
}
