# beep-boop

This script monitors our Google code and GitHub (Khan/khan-exercises) issues
and notifies us in a HipChat room when the bug report rates are far enough
above the mean rate to have a very high probability of being due to an abnormal
event (think a newly introduced bug). "Far enough above" is given by a Poisson
distribution with a certain probability threshold--if the probability of seeing
at least this number of bug reports due to random chance is low enough, we send
a notification, because it's likely that this elevated rate is due to a bug.
