import httplib

gh = httplib.HTTPSConnection("api.github.com")

gh.request("GET", "/repos/Khan/khan-exercises/issues?since=2012-07-06T22:11:11Z")
resp = gh.getresponse()
read = resp.read()
print (resp.status, hash(read), len(read))

gh2 = httplib.HTTPSConnection("api.github.com")

gh2.request("GET", "/repos/Khan/khan-exercises/issues")
resp2 = gh2.getresponse()
read2 = resp2.read()
print (resp2.status, hash(read2), len(read2))

gh.close()
gh2.close()
