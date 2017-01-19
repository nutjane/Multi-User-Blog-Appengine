import os
import re
import random
import hashlib
import hmac
from string import letters

import webapp2
import jinja2

from google.appengine.ext import db

template_dir = os.path.join(os.path.dirname(__file__), 'templates')
jinja_env = jinja2.Environment(loader = jinja2.FileSystemLoader(template_dir),
                               autoescape = True)

secret = 'fart'

def render_str(template, **params):
    t = jinja_env.get_template(template)
    return t.render(params)

def make_secure_val(val):
    return '%s|%s' % (val, hmac.new(secret, val).hexdigest())

def check_secure_val(secure_val):
    val = secure_val.split('|')[0]
    if secure_val == make_secure_val(val):
        return val

class BlogHandler(webapp2.RequestHandler):
    def write(self, *a, **kw):
        self.response.out.write(*a, **kw)

    def render_str(self, template, **params):
        params['user'] = self.user
        return render_str(template, **params)

    def render(self, template, **kw):
        self.write(self.render_str(template, **kw))

    def set_secure_cookie(self, name, val):
        cookie_val = make_secure_val(val)
        self.response.headers.add_header(
            'Set-Cookie',
            '%s=%s; Path=/' % (name, cookie_val))

    def read_secure_cookie(self, name):
        cookie_val = self.request.cookies.get(name)
        return cookie_val and check_secure_val(cookie_val)

    def login(self, user):
        self.set_secure_cookie('user_id', str(user.key().id()))

    def logout(self):
        self.response.headers.add_header('Set-Cookie', 'user_id=; Path=/')

    def initialize(self, *a, **kw):
        webapp2.RequestHandler.initialize(self, *a, **kw)
        uid = self.read_secure_cookie('user_id')
        self.user = uid and User.by_id(int(uid))

def render_post(response, post):
    response.out.write('<b>' + post.subject + '</b><br>')
    response.out.write(post.content)

class MainPage(BlogHandler):
  def get(self):
      self.write('Hello world!')

##### user stuff
def make_salt(length = 5):
    return ''.join(random.choice(letters) for x in xrange(length))

def make_pw_hash(name, pw, salt = None):
    if not salt:
        salt = make_salt()
    h = hashlib.sha256(name + pw + salt).hexdigest()
    return '%s,%s' % (salt, h)

def valid_pw(name, password, h):
    salt = h.split(',')[0]
    return h == make_pw_hash(name, password, salt)

def users_key(group = 'default'):
    return db.Key.from_path('users', group)

class User(db.Model):
    name = db.StringProperty(required = True)
    pw_hash = db.StringProperty(required = True)
    email = db.StringProperty()

    @classmethod
    def by_id(cls, uid):
        return User.get_by_id(uid, parent = users_key())

    @classmethod
    def by_name(cls, name):
        u = User.all().filter('name =', name).get()
        return u

    @classmethod
    def register(cls, name, pw, email = None):
        pw_hash = make_pw_hash(name, pw)
        return User(parent = users_key(),
                    name = name,
                    pw_hash = pw_hash,
                    email = email)

    @classmethod
    def login(cls, name, pw):
        u = cls.by_name(name)
        if u and valid_pw(name, pw, u.pw_hash):
            return u


##### blog stuff

def blog_key(name = 'default'):
    return db.Key.from_path('blogs', name)

class Post(db.Model):
    subject = db.StringProperty(required = True)
    content = db.TextProperty(required = True)
    created = db.DateTimeProperty(auto_now_add = True)
    last_modified = db.DateTimeProperty(auto_now = True)
    user = db.StringProperty(required = True)
    liked = db.StringListProperty()

    def render(self, template=""):
        self._render_text = self.content.replace('\n', '<br>')
        return render_str(template, p = self, user = self.user)

class Comment(db.Model):
    user_id = db.IntegerProperty(required=True)
    post_id = db.IntegerProperty(required=True)
    comment = db.TextProperty(required=True)
    created = db.DateTimeProperty(auto_now_add=True)
    last_modified = db.DateTimeProperty(auto_now=True)

    def getUserName(self):
        user = User.by_id(self.user_id)
        return user.name

    def render(self, template=""):
        self._render_text = self.comment.replace('\n', '<br>')
        return render_str(template, comment = self)


class BlogFront(BlogHandler):
    def get(self):
        posts = greetings = Post.all().order('-created')

        #for any error message
        msg = self.request.get('msg')

        self.render('front.html', posts = posts, msg=msg)

class PostPage(BlogHandler):
    def get(self, post_id):
        key = db.Key.from_path('Post', int(post_id), parent = blog_key())
        post = db.get(key)

        comments = db.GqlQuery("select * from Comment where post_id = " +
                               post_id + " order by created desc")

        #for any error message
        msg = self.request.get('msg')

        if not post:
            self.error(404)
            return

        self.render("permalink.html", post = post, comments = comments, msg=msg)


    def post(self, post_id):
        '''
            Post new comment
        '''
        key = db.Key.from_path('Post', int(post_id), parent = blog_key())
        post = db.get(key)
        comments = db.GqlQuery("select * from Comment where post_id = " +
                               post_id + " order by created desc")

        comment = self.request.get('comment')

        if not self.user:
            error = "Please Login First!"
            self.render("permalink.html", post = post, comments = comments, error=error, comment=comment)
            return

        user = self.user.key().id()

        if comment:
            c = Comment(parent = blog_key(), user_id=user, post_id=int(post_id), comment=comment)
            c.put()
            self.redirect('/blog/%s?msg=Commented Successfully' % str(post.key().id()))
        else:
            error = "You need to fill the comment first"
            self.render("permalink.html", post = post, msg=error, comment=comment)

class NewPost(BlogHandler):
    def get(self):
        if self.user:
            self.render("newpost.html")
        else:
            self.redirect("/login?msg=Please login first")

    def post(self):
        if not self.user:
            self.redirect('/blog?msg=please login')

        subject = self.request.get('subject')
        content = self.request.get('content')
        user = self.user.name

        if subject and content:
            p = Post(parent = blog_key(), subject = subject, content = content, user = user)
            p.put()
            self.redirect('/blog/%s' % str(p.key().id()))
        else:
            error = "You need to fill both subject and content."
            self.render("newpost.html", subject=subject, content=content, error=error)


class EditPost(BlogHandler):
    def get(self, post_id):
        if self.user:
            key = db.Key.from_path('Post', int(post_id), parent=blog_key())
            post = db.get(key)

            if not post:
                self.error(404)
                return

            if post.user == self.user.name:
                self.render("editpost.html", post = post)
            else:
                self.redirect('/blog')
        else:
            self.redirect('/blog')

    def post(self, post_id):
        if self.user:
            key = db.Key.from_path('Post', int(post_id), parent=blog_key())
            post = db.get(key)

            if not post:
                self.error(404)
                return

            if post.user == self.user.name:
                subject = self.request.get('subject')
                content = self.request.get('content')
                if subject and content:
                    post.subject = subject
                    post.content = content
                    post.put()
                    self.redirect('/blog/%s?msg=Successfully Edited ' % str(post.key().id()))
                else:
                    error = "You need to fill both subject and content."
                    self.render("editpost.html", post=post, error=error)
            else:
                self.redirect('/blog')

class DeletePost(BlogHandler):
    def get(self, post_id):
        if self.user:
            key = db.Key.from_path('Post', int(post_id), parent=blog_key())
            post = db.get(key)

            if not post:
                self.error(404)
                return

            if post.user == self.user.name:
                post.delete()

        self.redirect('/blog?msg=Deleted the post')

class LikePost(BlogHandler):
    def get(self, post_id):
        if self.user:
            key = db.Key.from_path('Post', int(post_id), parent=blog_key())
            post = db.get(key)

            if not post:
                self.error(404)
                return

            if post.user == self.user.name:
                self.redirect(self.request.referer)

            else:
                #check if this user has not liked yet
                if post.liked.count(self.user.name) == 0:
                    post.liked.append(self.user.name)
                    post.put()
                    self.redirect(self.request.referer)

                else:
                    post.liked.remove(self.user.name)
                    post.put()
                    self.redirect(self.request.referer)

        else:
            self.redirect('/login?msg=Please login first')


class EditComment(BlogHandler):
    def get(self, post_id, comment_id):
        if self.user:
            key = db.Key.from_path('Comment', int(comment_id), parent=blog_key())
            comment = db.get(key)

            if not comment:
                self.error(404)
                return

            if comment.getUserName() == self.user.name:
                self.render("editcomment.html", comment = comment)
            else:
                self.redirect('/blog/%s' % post_id)
        else:
            self.redirect('/blog/%s' % post_id)

    def post(self, post_id, comment_id):
        if self.user:
            key = db.Key.from_path('Comment', int(comment_id), parent=blog_key())
            comment = db.get(key)

            if not comment:
                self.error(404)
                return
            #if this user is authorized to edit this comment
            if comment.getUserName() == self.user.name:
                comment_value = self.request.get('comment')

                if comment:
                    comment.comment = comment_value
                    comment.put()
                    self.redirect('/blog/%s' % post_id)
                else:
                    error = "You need to fill both subject and content."
                    self.render("editcomment.html", comment=comment, error=error)
            else:
                self.redirect('/blog/%s' % post_id)

class DeleteComment(BlogHandler):
    def get(self, post_id, comment_id):
        if self.user:
            key = db.Key.from_path('Comment', int(comment_id), parent=blog_key())
            comment = db.get(key)

            if not comment:
                self.error(404)
                return
            #if this user is authorized to delete this comment
            if comment.getUserName() == self.user.name:
                comment.delete()

        self.redirect('/blog/%s' % post_id)

## user management

#regular expression for validation
USER_RE = re.compile(r"^[a-zA-Z0-9_-]{3,20}$")
def valid_username(username):
    return username and USER_RE.match(username)

PASS_RE = re.compile(r"^.{3,20}$")
def valid_password(password):
    return password and PASS_RE.match(password)

EMAIL_RE  = re.compile(r'^[\S]+@[\S]+\.[\S]+$')
def valid_email(email):
    return not email or EMAIL_RE.match(email)

class Signup(BlogHandler):
    def get(self):
        self.render("signup-form.html")

    def post(self):
        have_error = False
        self.username = self.request.get('username')
        self.password = self.request.get('password')
        self.verify = self.request.get('verify')
        self.email = self.request.get('email')

        params = dict(username = self.username,
                      email = self.email)

        if not valid_username(self.username):
            params['error_username'] = "That's not a valid username."
            have_error = True

        if not valid_password(self.password):
            params['error_password'] = "That wasn't a valid password."
            have_error = True
        elif self.password != self.verify:
            params['error_verify'] = "Your passwords didn't match."
            have_error = True

        if not valid_email(self.email):
            params['error_email'] = "That's not a valid email."
            have_error = True

        if have_error:
            self.render('signup-form.html', **params)
        else:
            self.done()

    def done(self, *a, **kw):
        raise NotImplementedError

class Register(Signup):
    def done(self):
        #make sure the username doesn't already exist
        u = User.by_name(self.username)
        if u:
            msg = 'That user already exists.'
            self.render('signup-form.html', error_username = msg)
        else:
            u = User.register(self.username, self.password, self.email)
            u.put()
            #Automatically login
            self.login(u)
            self.redirect('/blog')

class Login(BlogHandler):
    def get(self):
        msg = self.request.get('msg')
        self.render('login-form.html', msg=msg)

    def post(self):
        username = self.request.get('username')
        password = self.request.get('password')

        u = User.login(username, password)
        if u:
            self.login(u)
            self.redirect('/blog?msg=welcome!')
        else:
            msg = 'Invalid login'
            self.render('login-form.html', error = msg)

class Logout(BlogHandler):
    #To logout form the system
    def get(self):
        self.logout()
        self.redirect('/blog')

app = webapp2.WSGIApplication([('/', MainPage),
                               ('/blog/?', BlogFront),
                               ('/blog/([0-9]+)', PostPage),
                               ('/blog/newpost', NewPost),
                               ('/blog/like/([0-9]+)', LikePost),
                               ('/blog/edit/([0-9]+)', EditPost),
                               ('/blog/delete/([0-9]+)', DeletePost),
                               ('/blog/comment/edit/([0-9]+)/([0-9]+)', EditComment),
                               ('/blog/comment/delete/([0-9]+)/([0-9]+)', DeleteComment),
                               ('/signup', Register),
                               ('/login', Login),
                               ('/logout', Logout)
                               ],
                              debug=True)
